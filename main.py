from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html, get_redoc_html
from starlette.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from src.tuiwen import api_router
from src.tuiwen import settings
from src.tuiwen.utils.utils import get_version_from_pyproject, custom_generate_unique_id

__version__, description = get_version_from_pyproject("pyproject.toml")

# 标签描述配置
tags_metadata = [
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
]

# 服务地址
servers = [
    {"url": "https://api.tuiwen.alsoapp.com", "description": "生产环境地址"},
    {"url": "https://api-test.tuiwen.alsoapp.com", "description": "测试环境地址"},
    {"url": "http://127.0.0.1:8000", "description": "本地开发环境"},
]

app = FastAPI(title="内部API文档",
              description=description,
              version=__version__,
              debug=settings.DEBUG,
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
              generate_unique_id_function=custom_generate_unique_id
              )

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the ML model
    # app.state.pool = await get_async_pool()
    yield
    # Clean up the ML models and release the resources
    # app.state.pool.close()


app.include_router(api_router)

# 静态文件目录
app.mount("/static", StaticFiles(directory="static"), name="static")

##################################################### 中间件 ############################################################
# 允许的来源（这里是 * 表示所有域名, 你也可以指定特定的域名）
# 配置允许跨域的域名、请求方法等
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,  # 允许跨域访问的来源
    allow_credentials=True,  # 允许发送 cookies
    allow_methods=["*"],  # 允许所有 HTTP 方法，包括 OPTIONS
    allow_headers=["*"],  # 允许所有请求头
)


########################################### openapi样式文件自定义,如果时公网可关闭,使用默认CDN #####################
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
