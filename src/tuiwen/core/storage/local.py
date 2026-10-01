import asyncio
import inspect
import os
import shutil
from pathlib import Path
from typing import BinaryIO, Literal, TextIO, Any

from fastapi import UploadFile

from .base import Storage


class LocalStorage(Storage):
    def __init__(self, base_dir: str, static_prefix: str = "/static/videos", min_free_bytes: int = 10 * 1024**3):
        self.base_dir = Path(base_dir, self._get_ym())
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.static_prefix = static_prefix
        self.min_free_bytes = min_free_bytes

    @staticmethod
    def _open_file(path: Path, mode: Literal["rb", "wb"]) -> TextIO:
        return open(path, mode)

    def _check_space(self, need: int):
        usage = shutil.disk_usage(self.base_dir)
        if usage.free < need + self.min_free_bytes:
            raise RuntimeError("磁盘空间不足")

    async def save(self, name: str, content: Any, file_suffix: str, chunk_size: int = 1024 * 1024) -> str:
        print(f"debug ---> {self.base_dir}")
        target_dir: Path = self.base_dir / name
        target_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = target_dir / f"original{file_suffix}.tmp"
        final_file = target_dir / f"original{file_suffix}"

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

            # 原子替换
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
                except Exception as e:
                    pass

    async def open(self, name: str, mode: Literal["rb", "wb"] = "rb") -> BinaryIO:
        full = self.base_dir / name
        if not await asyncio.to_thread(full.exists):
            raise FileNotFoundError(name)
        return await asyncio.to_thread(self._open_file, full, mode)

    async def delete(self, name: str) -> None:
        full = self.base_dir / name
        if await asyncio.to_thread(full.exists):
            await asyncio.to_thread(full.unlink)

    async def exists(self, name: str) -> bool:
        return await asyncio.to_thread((self.base_dir / name).exists)

    async def size(self, name: str) -> int:
        full = self.base_dir / name
        stat = await asyncio.to_thread(full.stat)
        return stat.st_size

    async def url(self, name: str, **kwargs) -> str:
        return f"{self.static_prefix}/{name}"

    async def get_available_name(self, name: str) -> str:
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
        return str(self.base_dir / name)
