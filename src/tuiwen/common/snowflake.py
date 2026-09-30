import time
import threading

class SnowflakeGenerator:
    # Twitter snowflake
    def __init__(
        self,
        worker_id: int,
        epoch: int = 1704067200000,  # 2024-01-01 00:00:00 毫秒
    ):
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
        return int(time.time() * 1000)

    def _wait_next_millis(self, last_ts: int) -> int:
        ts = self._current_millis()
        while ts <= last_ts:
            ts = self._current_millis()
        return ts

    def next_id(self) -> int:
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
import os
WORKER_ID = int(os.getenv("SNOWFLAKE_WORKER_ID", 0))
snow_gen = SnowflakeGenerator(worker_id=WORKER_ID)

def gen_snowflake_id() -> int:
    return snow_gen.next_id()

# 使用示例
if __name__ == "__main__":
    vid = snow_gen.next_id()
    print(vid, type(vid))
