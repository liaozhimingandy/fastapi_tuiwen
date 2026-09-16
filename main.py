"""应用入口: 组装 FastAPI 实例、生命周期、中间件与文档页。

启动流程(lifespan):
    打印 banner → 初始化 Redis(失败即自杀) → 初始化 PostgreSQL 连接/连接池
    → 初始化全局邮件服务 → 对外提供服务
停机流程: 关闭 asyncpg 连接池 → dispose SQLAlchemy 引擎 → 关闭 Redis
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.openapi.docs import get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html, get_redoc_html
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse

from src.tuiwen import (api_router, logger, custom_generate_unique_id,
                        get_version_from_txt, get_settings, dispose_engine, close_async_pool, init_mail_sender,
                        init_redis, close_redis, init_postgres)


# 版本号与描述从 VERSION 文件首行读取(CI/CD 可只改该文件)
__version__, description = get_version_from_txt("VERSION")

# 标签描述配置(对应 core.config.Tag 与各路由的 tags, 决定文档页分组显示)
tags_metadata = [
    {
        "name": "health",
        "description": "服务健康状态检查.",
    },
    {
        "name": "oauth",
        "description": "和token获取相关操作.",
    },
    {
        "name": "account",
        "description": "账号相关操作.",
    },
    {
        "name": "post",
        "description": "和帖子相关操作.",
        "externalDocs": {
            "description": "内部文档",
            "url": "https://www.alsoapp.com/",
        },
    },
    {
        "name": "comment",
        "description": "和评论相关操作.",
    },
    {
        "name": "like",
        "description": "和点赞相关操作.",
    },
    {
        "name": "upload",
        "description": "和文件上传相关操作.",
    },
    {
        "name": "follow",
        "description": "和关注操作相关.",
    },
    {
        "name": "more",
        "description": "其它",
    },
]

# 服务地址(文档页右上角可切换调试的服务端)
servers = [
    {"url": "https://api.tuiwen.alsoapp.com", "description": "生产环境地址"},
    {"url": "https://api-test.tuiwen.alsoapp.com", "description": "测试环境地址"},
    {"url": "http://127.0.0.1:8000", "description": "本地开发环境"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """app生命周期函数: yield 之前是启动逻辑, 之后是停机清理。"""
    # app 启动前
    # app.state.pool = await get_async_pool()

    # 初始化数据库
    # from src.tuiwen.core import init_db
    # await init_db()
    # logger.info("init database success")
    # NOTE: 建表已注释, 表结构当前依赖数据库侧脚本/人工维护; 若要启用请先补
    #       core.database._import_all_models() 的模型导入(现为空函数)

    # 启动横幅(纯展示, 与业务无关)
    from pyfiglet import Figlet
    ft = Figlet(font="ansi_shadow")
    ascii_art = ft.renderText("API-TUIWEN")
    cleaned_lines = [line.rstrip() for line in ascii_art.split("\n")]
    final_art = "\n".join(cleaned_lines).rstrip("\n")  # 去除整个文本的末尾换行符
    print(final_art)
    print(f'version: {__version__} doc_url: http://localhost:8000/docs/')
    logger.info("✅ server started")

    import os, signal
    # 1. Redis 初始化(缓存/验证码依赖, 属强依赖: 失败即终止进程, 避免半可用状态)
    # NOTE: 直接 kill 自身进程, 容器编排下表现为反复重启; 可用 sys.exit(1) 起同样效果且更易读
    try:
        await init_redis()
        logger.info("✅ Redis 同步连接初始化成功")
    except Exception as e:
        logger.error("【FATAL】Redis 核心组件连接失败，服务无法启动")
        os.kill(os.getpid(), signal.SIGTERM)

    # 2. PostgreSQL 初始化
    try:
        await init_postgres()
    except Exception as e:
        logger.error("【FATAL】PostgreSQL 数据库初始化失败，服务无法启动: %s", e)
        os.kill(os.getpid(), signal.SIGTERM)

    # 邮件系统(按 DEBUG 自动切本地 MailDev / 生产 SMTP)
    init_mail_sender(is_prod=not get_settings().DEBUG)
    logger.info("✅ 全局邮件服务初始化完成")
    logger.info(f"✅ 系统启动成功,正在以[{ '测试' if get_settings().DEBUG else '生产' }]环境运行❗")
    yield   # ← 服务对外可用期间
    # 停机：释放所有连接资源
    # NOTE: 裸 except 会吞掉清理阶段的异常, 排查停机问题时建议至少 logger.warning 记录下来
    try:
        await close_async_pool()
        await dispose_engine()
        await close_redis()
    except:
        pass


# 应用实例: 关掉默认 docs/redoc, 改为下方自定义(静态资源走本地 /static, 便于内网部署)
app = FastAPI(title="内部API文档",
              description=description,
              version=__version__,
              debug=get_settings().DEBUG,
              terms_of_service="https://www.alsoapp.com/terms/",
              contact={
                  "name": "廖志明",
                  "url": "https://www.alsoapp.com/",
                  "email": "liaozhimingandy@qq.com",
              },
              license_info={
                  "name": "Apache 2.0",
                  "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
              },
              openapi_tags=tags_metadata,
              servers=servers,
              docs_url=None,
              redoc_url=None,
              generate_unique_id_function=custom_generate_unique_id,
              lifespan=lifespan,
              redirect_slashes=True,
              )

# 挂载业务路由(总前缀 /api/v2, 由 api/router.py 定义)
app.include_router(api_router)

# 静态文件目录(前端 swagger 资源、上传的媒体文件均由此对外暴露)
app.mount("/static", StaticFiles(directory="static"), name="static")

##################################################### 中间件 ############################################################
# 跨域中间件: 允许跨域的域名、请求方法、请求头
# NOTE: allow_credentials=True 与 allow_origins=["*"] 组合会被浏览器拒绝(规范禁止),
#       生产环境应把 BACKEND_CORS_ORIGINS 配成具体域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().BACKEND_CORS_ORIGINS,  # 允许跨域访问的来源
    allow_credentials=True,  # 允许发送 cookies
    allow_methods=["*"],  # 允许所有 HTTP 方法，包括 OPTIONS
    allow_headers=["*"],  # 允许所有请求头
)


########################################### openapi样式文件自定义,如果时公网可关闭,使用默认CDN #####################
# 三个文档页均使用本地 /static 下的资源(不依赖公网 CDN, 适合内网/离线环境)
@app.get("/docs", include_in_schema=False, tags=["docs"])
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - openapi",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
    )


@app.get(app.swagger_ui_oauth2_redirect_url, include_in_schema=False, tags=["docs"])
async def swagger_ui_redirect():
    return get_swagger_ui_oauth2_redirect_html()


@app.get("/redoc", include_in_schema=False, tags=["docs"])
async def redoc_html():
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=app.title + " - ReDoc",
        redoc_js_url="/static/redoc.standalone.js",
    )

# @app.exception_handler(HTTPException)
# async def custom_http_exception_handler(request, exc):
#     # 统一异常处理
#     return JSONResponse(
#         status_code=exc.status_code,
#         content={"message": f"Oops! {exc.detail} occurred"},
#     )
