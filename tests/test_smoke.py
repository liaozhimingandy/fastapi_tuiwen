"""应用装配冒烟: 保证 main.py 能导入、路由能装配、OpenAPI 能生成。

这类用例跑得比端到端测试快两个数量级, 却能在「改了模型/依赖注入后忘记改引用」
时立刻报错 —— 历史上 import 级错误(如模型字段改名)就是这么漏到运行期的。
"""


def test_app_imports():
    """导入 main 即完成 FastAPI 实例组装(不触发 lifespan, 不会连数据库)。"""
    from main import app

    assert app.title
    assert app.version


def test_openapi_schema_generated():
    """OpenAPI 能生成, 且业务路由确实挂到了 /api/v2 前缀下。

    NOTE: 只要任一 response_model / 依赖签名不合法, openapi() 就会抛异常,
          因此这一步同时校验了全部接口的出入参模型定义。
    """
    from main import app

    schema = app.openapi()
    paths = schema["paths"]

    assert len(paths) >= 30, f"路由数量异常(可能未挂载): {len(paths)}"
    assert any(p.startswith("/api/v2/") for p in paths), "业务路由未挂到 /api/v2"
    assert "/api/v2/health-check/" in paths, "健康检查路由缺失"


def test_core_docs_and_static_mounted():
    """文档页与静态资源目录已挂载(文档页依赖 /static 下的本地 swagger 资源)。"""
    from main import app

    paths = {getattr(r, "path", None) for r in app.routes}

    assert "/static" in paths
    assert "/docs" in paths or "docs" in paths
