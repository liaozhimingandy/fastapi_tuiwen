"""离线单元测试的公共前置。

这里的用例必须「零外部依赖」: 不连 PostgreSQL / Redis / SMTP, 只做
导入、模型元数据、纯函数与契约层面的校验, 因此可以在任意机器上秒级跑完,
作为 CI 的第一道关卡。需要真实依赖的端到端用例仍在仓库根目录的 test_main.py。

NOTE: 环境变量必须在导入 src.tuiwen 之前设置 —— Settings 是 lru_cache 单例,
      一旦被导入就固定; 而 core.database 在模块级就会用这些配置构造引擎。
"""
import os

os.environ.setdefault("DOCKER_MODE", "1")          # 关闭 .env.develop 加载, 完全走环境变量
os.environ.setdefault("DEBUG", "true")             # 避免强制要求 SECRET_KEY 之外的额外约束
os.environ.setdefault("SECRET_KEY", "ci-test-secret-key")
os.environ.setdefault("BACKEND_CORS_ORIGINS", "http://localhost")
os.environ.setdefault("VIDEO_ALLOW_SUFFIX", ".mp4,.mov,.mkv")
os.environ.setdefault("POSTGRES_DB", "tuiwen_unit")
os.environ.setdefault("REDIS_HOST", "127.0.0.1")
