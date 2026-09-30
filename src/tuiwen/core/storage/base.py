import abc
import datetime
from pathlib import Path
from typing import BinaryIO


class Storage(abc.ABC):
    """
    文件存储抽象基类（参考 Django Storage 设计）

    统一文件语义：所有方法基于「相对 key」操作（如 202609/12345/video.mp4），
    与底层(本地磁盘/S3)无关。业务层只依赖本基类。
    """

    # ---------- 必须实现的抽象接口 ----------
    @abc.abstractmethod
    async def save(self, name: str, content: BinaryIO) -> str:
        """
        保存文件（Django风格）
        :param name: 文件key
        :param content: 类文件对象 BinaryIO，后端逐块读取，不一次性加载全部到内存
        :return: 最终存储key
        """

    @abc.abstractmethod
    async def open(self, name: str, mode: str = "rb") -> BinaryIO:
        """打开文件，返回文件句柄（本地=文件对象；S3=读取流）"""

    @abc.abstractmethod
    async def delete(self, name: str) -> None:
        """删除文件，不存在时静默"""

    @abc.abstractmethod
    async def exists(self, name: str) -> bool:
        """文件是否存在"""

    @abc.abstractmethod
    async def size(self, name: str) -> int:
        """返回文件大小（字节）"""

    @abc.abstractmethod
    async def url(self, name: str) -> str:
        """生成可访问的 URL"""

    @abc.abstractmethod
    async def get_available_name(self, name: str) -> str:
        """返回可用的文件名（处理重名冲突）"""

    # ---------- 基类提供的通用工具（子类可覆盖） ----------
    async def path(self, name: str) -> str:
        """返回本地文件系统路径（仅本地存储有意义，S3 抛异常）"""
        raise NotImplementedError("当前存储后端不支持本地文件路径")

    @staticmethod
    def _get_ym() -> str:
        """统一年月分区，避免各处重复计算"""
        return datetime.datetime.now().strftime("%Y%m")

    @staticmethod
    def get_valid_name(name: str) -> str:
        """清洗文件名：去路径、去非法字符、保证安全"""
        name = Path(name).name  # 去掉目录，防路径穿越
        name = name.replace("..", "").replace("/", "").replace("\\", "")
        return name or "file"
