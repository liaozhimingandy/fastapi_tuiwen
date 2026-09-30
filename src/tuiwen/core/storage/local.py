import asyncio
import os
import shutil
from pathlib import Path
from typing import BinaryIO, Literal
from .base import Storage


class LocalStorage(Storage):
    def __init__(self, base_dir: str, static_prefix: str = "/static/videos", min_free_bytes: int = 10 * 1024**3):
        self.base_dir = Path(base_dir, self._get_ym())
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.static_prefix = static_prefix
        self.min_free_bytes = min_free_bytes

    @staticmethod
    def _open_file(path: Path, mode: Literal["rb", "wb"]) -> BinaryIO:
        return open(path, mode)

    def _check_space(self, need: int):
        usage = shutil.disk_usage(self.base_dir)
        if usage.free < need + self.min_free_bytes:
            raise RuntimeError("磁盘空间不足")

    async def save(self, name: str, content: BinaryIO) -> str:
        target = self.base_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_suffix(".part")

        f = await asyncio.to_thread(self._open_file, tmp_path, "wb")
        try:
            # 逐块读取类文件对象，写入本地，不一次性加载全部内容
            chunk_size = 1024 * 1024
            while chunk := await asyncio.to_thread(content.read, chunk_size):
                await asyncio.to_thread(f.write, chunk)

            await asyncio.to_thread(f.flush)
            await asyncio.to_thread(os.fsync, f.fileno())
            await asyncio.to_thread(os.replace, tmp_path, target)
        except Exception:
            await asyncio.to_thread(f.close)
            if await asyncio.to_thread(tmp_path.exists):
                await asyncio.to_thread(tmp_path.unlink)
            raise
        finally:
            await asyncio.to_thread(f.close)
        return name

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

    async def url(self, name: str) -> str:
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
