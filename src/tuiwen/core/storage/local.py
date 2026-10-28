"""本地磁盘存储后端。

实现 Storage 抽象基类, 把「相对 key」映射到 <base_dir>/<YYYYMM>/<key> 下的真实文件:
    原始文件: <base_dir>/<YYYYMM>/<key>/original<suffix>
    目录结构: 每个 key 独占一个目录, 便于后续 HLS 分片、封面等产物放在同一处。

写入策略:
    先写 original<suffix>.tmp, fsync 落盘后再 os.replace 原子替换成正式文件名,
    避免「文件只写了一半」被当成有效产物; 任何异常都会清理临时文件。

注意: base_dir 在实例化时就把年月拼进去, 是进程级固定值(见 Storage 的 get_storage 单例),
      跨月不切换分区 —— 长期运行的容器需要按此预期排查文件落点。
"""
import asyncio
import inspect
import os
import shutil
from pathlib import Path
from typing import BinaryIO, Literal, TextIO, Any

from fastapi import UploadFile

from .base import Storage


class LocalStorage(Storage):
    """本地文件系统存储实现。

    所有 IO 都通过 asyncio.to_thread 丢到线程池执行, 避免阻塞事件循环;
    对外方法签名与 Storage 基类保持一致, 业务层不需要感知底层是本地还是对象存储。
    """

    def __init__(self, base_dir: str, static_prefix: str = "/static/medias/videos", min_free_bytes: int = 10 * 1024**3):
        """
        Args:
            base_dir: 磁盘根目录, 实例化时会自动拼上当前年月(YYYYMM)作为分区
            static_prefix: 对外 URL 前缀, 与 FastAPI 的 static mount 对应
            min_free_bytes: 最小剩余空间保护水位(默认 10GB), 写入前低于该值直接拒绝
        """
        # NOTE: 年月在这里一次性算死, 跨月不会自动滚动到新分区
        self.base_dir = Path(base_dir, self._get_ym())
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.static_prefix = static_prefix
        self.min_free_bytes = min_free_bytes

    @staticmethod
    def _open_file(path: Path, mode: Literal["rb", "wb"]) -> TextIO:
        """同步打开文件(供 to_thread 调用)。"""
        return open(path, mode)

    def _check_space(self, need: int):
        """检查磁盘剩余空间是否够写入 need 字节且仍高于保护水位。

        Raises:
            RuntimeError: 剩余空间不足
        """
        usage = shutil.disk_usage(self.base_dir)
        if usage.free < need + self.min_free_bytes:
            raise RuntimeError("磁盘空间不足")

    async def save(self, name: str, content: Any, file_suffix: str, chunk_size: int = 1024 * 1024) -> str:
        """流式保存文件到 <base_dir>/<name>/original<suffix>。

        自动适配同步/异步读取对象: UploadFile 用 await read(), 普通 BinaryIO 走线程池,
        因此调用方传哪种都能工作。按 chunk_size 分块, 不会把整个文件读进内存。

        Args:
            name: 存储 key(通常是 video_id), 同时作为目录名
            content: 带 read(size) 方法的文件对象(UploadFile / BinaryIO)
            file_suffix: 文件后缀, 含点, 如 ".mp4"
            chunk_size: 单次读取字节数, 默认 1MB

        Returns:
            str: 传入的 name(业务侧据此拼 URL)

        Raises:
            Exception: 写入过程中的任何异常, 抛出前会清理 .tmp 临时文件
        """
        target_dir: Path = self.base_dir / name
        target_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = target_dir / f"original{file_suffix}.tmp"
        final_file = target_dir / f"original{file_suffix}"

        # 写入前先做一次磁盘水位检查(流式上传无法预知总大小, 这里保证剩余空间
        # 至少高于 min_free_bytes 保护线; need=0 表示不额外预估本次写入量)
        self._check_space(0)

        f = None
        try:
            # 打开临时文件
            f = await asyncio.to_thread(open, tmp_path, "wb")
            # 判断 read 是同步还是异步
            read_method = content.read
            is_async_read = inspect.iscoroutinefunction(read_method)

            # 流式读取
            while True:
                if is_async_read:
                    # UploadFile 等异步对象
                    chunk = await read_method(chunk_size)
                else:
                    # BinaryIO 等同步对象
                    chunk = await asyncio.to_thread(read_method, chunk_size)
                if not chunk:
                    break
                # 写文件
                await asyncio.to_thread(f.write, chunk)
            # flush
            await asyncio.to_thread(f.flush)
            # 确保落盘
            await asyncio.to_thread(os.fsync, f.fileno())
            # 关闭文件
            await asyncio.to_thread(f.close)
            f = None

            # 原子替换(同分区内 rename, 不会出现半个文件对外可见)
            await asyncio.to_thread(os.replace, tmp_path, final_file)
            return name

        except Exception:
            if f is not None:
                try:
                    await asyncio.to_thread(f.close)
                except Exception:
                    pass
            try:
                if await asyncio.to_thread(tmp_path.exists):
                    await asyncio.to_thread(tmp_path.unlink)
            except Exception:
                pass
            raise

        finally:
            if f is not None:
                try:
                    await asyncio.to_thread(f.close)
                except Exception:
                    pass

    async def open(self, name: str, mode: Literal["rb", "wb"] = "rb") -> BinaryIO:
        """打开文件句柄; 文件不存在时抛 FileNotFoundError(不做隐式创建)。"""
        full = self.base_dir / name
        if not await asyncio.to_thread(full.exists):
            raise FileNotFoundError(name)
        return await asyncio.to_thread(self._open_file, full, mode)

    async def delete(self, name: str) -> None:
        """删除文件; 不存在时静默返回(幂等)。"""
        full = self.base_dir / name
        if await asyncio.to_thread(full.exists):
            await asyncio.to_thread(full.unlink)

    async def exists(self, name: str) -> bool:
        """判断 key 对应的路径是否存在(注意是文件或目录, 由 name 决定)。"""
        return await asyncio.to_thread((self.base_dir / name).exists)

    async def size(self, name: str) -> int:
        """返回文件字节数; 不存在时由底层 stat 抛 FileNotFoundError。"""
        full = self.base_dir / name
        stat = await asyncio.to_thread(full.stat)
        return stat.st_size

    async def url(self, name: str, **kwargs) -> str:
        """拼对外访问地址: <static_prefix>/<name>。

        **kwargs 仅为兼容基类签名(如 S3 的过期时间参数), 本地存储无需使用。
        """
        return f"{self.static_prefix}/{name}"

    async def get_available_name(self, name: str) -> str:
        """重名时追加 _1 / _2 ... 直到可用, 最多尝试 9999 次。

        Raises:
            RuntimeError: 候选名全部被占用
        """
        if not await self.exists(name):
            return name
        p = Path(name)
        stem, suffix = p.stem, p.suffix
        for i in range(1, 10000):
            candidate = f"{stem}_{i}{suffix}"
            if not await self.exists(candidate):
                return candidate
        raise RuntimeError("无法生成唯一文件名")

    async def path(self, name: str) -> str:
        """返回本地绝对路径, 供需要直接把路径交给外部程序(如 ffmpeg)的场景使用。"""
        return str(self.base_dir / name)
