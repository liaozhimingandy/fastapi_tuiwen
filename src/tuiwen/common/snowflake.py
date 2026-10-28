"""Twitter Snowflake 分布式 ID 生成器。

64 位 ID 结构(从高位到低位):
    1 位符号位(恒 0) | 41 位毫秒时间戳(相对 epoch) | 10 位 worker_id | 12 位序列号

按 1024 个 worker、每毫秒 4096 个 ID 计算, 单机峰值约 409 万 ID/秒;
41 位时间戳可支撑约 69 年(从 epoch 2024-01-01 起算)。

部署要求:
    多实例部署必须给每个实例配置不同的 SNOWFLAKE_WORKER_ID(0~1023),
    否则不同实例在同一毫秒可能生成完全相同的 ID。
"""
import os
import time
import threading


class SnowflakeGenerator:
    """线程安全的雪花 ID 生成器(单实例内用 Lock 串行化, 保证序列号不冲突)。"""

    # Twitter snowflake
    def __init__(
        self,
        worker_id: int,
        epoch: int = 1704067200000,  # 2024-01-01 00:00:00 毫秒
    ):
        """
        Args:
            worker_id: 机器/实例编号, 取值 0~1023, 多实例部署必须互不相同
            epoch: 时间戳起点(毫秒), 一旦上线不可再改, 否则可能生成重复 ID

        Raises:
            ValueError: worker_id 越界
        """
        # 校验worker id范围 0~1023
        if not (0 <= worker_id <= 1023):
            raise ValueError("worker_id must be between 0 and 1023")

        self.epoch = epoch
        self.worker_id = worker_id

        self.worker_id_bits = 10
        self.sequence_bits = 12

        self.max_sequence = (1 << self.sequence_bits) - 1
        self.worker_shift = self.sequence_bits
        self.timestamp_shift = self.sequence_bits + self.worker_id_bits

        self._lock = threading.Lock()
        self._last_timestamp: int = -1
        self._sequence: int = 0

    def _current_millis(self) -> int:
        """当前 UNIX 毫秒时间戳。"""
        return int(time.time() * 1000)

    def _wait_next_millis(self, last_ts: int) -> int:
        """自旋等待时钟走到 next 毫秒(同一毫秒内 4096 个序列号耗尽时调用)。

        单次等待通常 <1ms, 用忙等换取实现简单; 若 QPS 极高可改为 sleep 微秒级退避。
        """
        ts = self._current_millis()
        while ts <= last_ts:
            ts = self._current_millis()
        return ts

    def next_id(self) -> int:
        """生成下一个 64 位 ID。

        Returns:
            int: 单调递增的雪花 ID

        Raises:
            RuntimeError: 检测到时钟回拨(系统时间被往回调整), 直接拒绝生成,
                          避免在同一毫秒区间重复产出 ID
        """
        with self._lock:
            ts = self._current_millis()

            # 时钟回拨，禁止生成
            if ts < self._last_timestamp:
                raise RuntimeError(f"Clock moved backwards. Refuse generate id. last_ts={self._last_timestamp}, now={ts}")

            if ts == self._last_timestamp:
                self._sequence = (self._sequence + 1) & self.max_sequence
                # 当前毫秒序列号耗尽，等待下一毫秒
                if self._sequence == 0:
                    ts = self._wait_next_millis(self._last_timestamp)
            else:
                self._sequence = 0

            self._last_timestamp = ts

            timestamp_part = (ts - self.epoch) << self.timestamp_shift
            worker_part = self.worker_id << self.worker_shift
            final_id = timestamp_part | worker_part | self._sequence
            return final_id


# ====================== FastAPI全局单例 ======================
# worker_id 从环境变量读取！多实例部署每个实例不一样
WORKER_ID = int(os.getenv("SNOWFLAKE_WORKER_ID", 0))
snow_gen = SnowflakeGenerator(worker_id=WORKER_ID)


def gen_snowflake_id() -> int:
    """模块级便捷函数: 从全局单例取一个新 ID(业务代码统一走这里)。"""
    return snow_gen.next_id()


# 使用示例
if __name__ == "__main__":
    vid = snow_gen.next_id()
    print(vid, type(vid))
