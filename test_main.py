#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： test_main.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2025/2/15 21:31
    @Desc: 端到端接口测试(TestClient 走真实 lifespan)

           依赖外部服务: PostgreSQL / Redis / 邮件服务(MailDev) 均需就绪,
           且 Redis 中能取到验证码, 属集成测试而非单元测试。
           执行前提: 先启动服务依赖, 再 `pytest test_main.py`
=================================================
"""
from collections.abc import Generator
from datetime import datetime
import random
import unittest
import uuid
from hashlib import md5

import pytz
import pytest
import redis
from starlette.testclient import TestClient
from fastapi import status

from main import app
from src.tuiwen import get_settings
from src.tuiwen.utils.redis_util import RedisKey


# 旧方案: 直连已启动的服务(需先 uvicorn 起服务); 现改为 TestClient 进程内调用, 无需起服务
# @pytest.fixture(scope="module")
# def client() -> Generator[TestClient, None, None]:
#     with httpx.Client(base_url="http://127.0.0.1:8000") as c:
#         yield c

@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    """模块级共享的 TestClient。

    进入上下文即触发 app.lifespan: 会连 Redis / PostgreSQL / 初始化邮件服务,
    环境不就绪时整个测试模块都会失败。
    """
    with TestClient(app, client=('127.0.0.1', 9080), base_url='http://127.0.0.1:8000/api/v2') as c:
        yield c



# @pytest.fixture(scope="session", autouse=True)
# def session() -> Generator[Session, None, None]:
#     with Session(create_engine("postgresql+psycopg://zhiming:zhiming@localhost:5432/tuiwen")) as session:
#         yield session
config = get_settings()

# 全局单例，同步redis客户端，仅测试使用
_sync_redis: redis.Redis | None = None

def get_sync_redis() -> redis.Redis:
    """同步 Redis 客户端单例(测试内直接读缓存, 例如取邮箱验证码)。"""
    global _sync_redis
    if _sync_redis is None:
        _sync_redis = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            password=config.REDIS_PASSWORD,
            db=config.REDIS_DB,
            decode_responses=True,
            socket_timeout=5,
        )
        _sync_redis.ping()
    return _sync_redis

def redis_sync_get(key: str):
    """按 key 读取 Redis 值(主要用于从缓存里捞验证码)。"""
    cli = get_sync_redis()
    return cli.get(key)


class TestMain:
    """测试类

    用例之间通过类属性串联上下文(account_id / post_id / comment_id / snap_id),
    因此执行顺序敏感, 不建议单独运行某个用例。
    NOTE: md5_hash 是类级共享的 md5 对象, update 后状态会跨用例累积,
          变更密码类用例依赖它保持同值, 修改时要留意
    """
    BASE_URL = "http://127.0.0.1:8000/api/v2"
    account_id = ''
    post_id = ''
    comment_id = ''
    followee_id = ''
    md5_hash = md5()
    snap_id = ""

    @pytest.fixture(scope="class", autouse=True)
    def test_register_and_login(self, client: TestClient):
        """类级前置: 随机邮箱注册一个新账号并登录, 把 token 注入 client。

        Returns:
            dict: account_id / mail / refresh_token / 已带 Authorization 头的 client,
                  后续用例通过 test_register_and_login.get(...) 取用
        """

        passowrd = '123456'
        TestMain.md5_hash.update(passowrd.encode('utf-8'))
        data = {
            "mail": f"test-user{random.randint(1, 20000)}@test-user-ap.com",
            "password": TestMain.md5_hash.hexdigest(),
            "nickname": "test",
            "birthday": datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d'),
            "area_code": "CHN",
            "sex": 0,
            "avatar": ""
        }
        print(data)
        # with httpx.Client() as client:
        r = client.post("/accounts/register/", json=data,
                        headers={"Content-Type": "application/json"})
        assert r.status_code == status.HTTP_201_CREATED, f'注册失败: {r.text}'
        TestMain.account_id = r.json().get('account_id')
        username = r.json().get('username')
        account_id = r.json().get('account_id')
        mail = data.get('mail')

        #     登录逻辑
        form_data = {
            "username": username,
            "password": TestMain.md5_hash.hexdigest(),
        }

        r = client.post("/oauth/authorize/password/", data=form_data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert r.status_code == 200, f"登录失败: {r.text}"
        token_data = r.json()
        access_token = token_data.get('access_token')
        refresh_token = token_data.get('refresh_token')
        # 更新token到client
        client.headers.update({"Authorization": f"Bearer {access_token}"})

        # --- 返回上下文数据给后续测试使用 ---
        return {
            "account_id": account_id,
            "mail": mail,
            "refresh_token": refresh_token,
            "client": client  # 把配置好 token 的 client 也传回去
        }

    # ==================== 会话 / 账号 ====================
    def test_refresh_token(self, test_register_and_login) -> None:
        """测试刷新token"""
        r = test_register_and_login.get('client').get(f'/oauth/refresh-token/{TestMain.account_id}/refresh_token/',
                                                      headers={"Content-Type": "application/json",
                                                               "Authorization": f"Bearer {test_register_and_login.get('refresh_token')}"})
        assert r.status_code == 200, r.json()
        access_token = r.json().get('access_token')
        test_register_and_login.get('client').headers.update({"Authorization": f"Bearer {access_token}"})

    def test_health_check(self, test_register_and_login) -> None:
        """测试健康检查"""
        # 直接使用 httpx 发送同步 HTTP 请求
        r = test_register_and_login.get('client').get("/health-check/")
        assert r.status_code == 200

    def test_get_account(self, test_register_and_login) -> None:
        """获取帐户信息"""
        account_id = test_register_and_login.get('account_id')
        # ok
        r = test_register_and_login.get('client').get(f"/accounts/{account_id}/")
        assert r.status_code == 200
        # 404: 合法但不存在的 uuid7
        r = test_register_and_login.get('client').get(f"/accounts/{uuid.uuid7()}/")
        assert r.status_code == status.HTTP_404_NOT_FOUND
        # 422: 非法 uuid 在路径参数校验阶段即被拒, 不会打到数据库
        r = test_register_and_login.get('client').get(f"/accounts/{account_id}xx/")
        assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_account_search(self, test_register_and_login) -> None:
        """搜索功能"""
        keyword = "test"
        # ok
        r = test_register_and_login.get('client').get(f"/accounts/search/{keyword}/")
        assert r.status_code == 200

        # 404
        r = test_register_and_login.get('client').get(f"/accounts/search/{keyword}-{str(uuid.uuid7())}/")
        assert r.status_code == status.HTTP_200_OK and r.json().get('total') == 0

    def test_put_account(self, test_register_and_login) -> None:
        """更新帐户信息"""
        data = {
            "nickname": "测试test",
        }
        client = test_register_and_login.get('client')
        response = client.put(f"/accounts/{TestMain.account_id}/", json=data)
        assert response.status_code == 200

    def test_account_send_code(self, test_register_and_login) -> None:
        """发送验证码"""
        client = test_register_and_login.get('client')

        payload = {
            "channel": "mail",
            "account": test_register_and_login.get('mail'),
            "scene": "reset_pwd"
        }
        r = client.post("/accounts/send/code/", json=payload)
        assert r.status_code == status.HTTP_200_OK

    def test_password_change(self, test_register_and_login) -> None:
        """测试密码修改"""
        data = {
            "account_id": TestMain.account_id,
            "password_current": TestMain.md5_hash.hexdigest(),
            "password_new": TestMain.md5_hash.hexdigest()
        }
        client = test_register_and_login.get('client')
        r = client.put('/accounts/password/change/', json=data)
        assert r.status_code == status.HTTP_400_BAD_REQUEST, r.json()

        new_md5 = md5()
        new_md5.update('test'.encode('utf-8'))
        # 200
        data = {
            "account_id": TestMain.account_id,
            "password_current": TestMain.md5_hash.hexdigest(),
            "password_new": new_md5.hexdigest()
        }
        client = test_register_and_login.get('client')
        r = client.put('/accounts/password/change/', json=data)
        assert r.status_code == status.HTTP_200_OK, r.json()

    def test_password_reset(self, test_register_and_login) -> None:
        """密码重置"""
        # 提取验证码
        redis_key = RedisKey.reset_pwd_code(test_register_and_login.get('account_id'))
        # 从 Redis 获取验证码
        correct_code = redis_sync_get(redis_key)
        assert correct_code is not None

        data = {
            "username": test_register_and_login.get('mail'),
            "password": TestMain.md5_hash.hexdigest(),
            "code": correct_code
        }
        client = test_register_and_login.get('client')
        r = client.put('/accounts/password/reset/', json=data)
        assert r.status_code == status.HTTP_200_OK, r.json()
        # 测试验证码不对的情况
        data['code'] = "666777"
        r = client.put('/accounts/password/reset/', json=data)
        assert r.status_code == status.HTTP_400_BAD_REQUEST

    # ==================== 帖子 ====================
    def test_create_post(self, test_register_and_login) -> None:
        """创建帖子"""
        data = {
            "content": {},
            "post_type": 1,
            "account_id": TestMain.account_id,
            "from_device": 9,
            "right_status": 1,
            "location": "string",
            "is_top": False
        }
        client = test_register_and_login.get('client')
        r = client.post('/posts/', json=data)
        assert r.status_code == status.HTTP_201_CREATED
        TestMain.post_id = r.json().get('post_id')


    def test_get_posts_latest(self, test_register_and_login) -> None:
        """获取最新帖子"""
        client = test_register_and_login.get('client')
        r = client.get("/posts/", params={"limit": 10})
        assert r.status_code == 200 and r.json()['total'] > 0, "帖子数量为0"

    def test_get_account_posts(self, test_register_and_login) -> None:
        """按游标取某账号的帖子

        NOTE: 断言 total == 0 但提示语写的是"帖子数量为0", 语义相反;
              且游标用的是刚创建的 post_id, 返回 0 条属预期, 作者本意应是校验"游标之后无数据"
        """
        client = test_register_and_login.get('client')

        r = client.get(f'/posts/accounts/{TestMain.account_id}/', params={'limit': 10, 'cursor': TestMain.post_id})
        assert r.status_code == 200
        assert r.json()['total'] == 0, "帖子数量为0"

    def test_update_post_right(self, test_register_and_login) -> None:
        """测试更新帖子状态"""
        data = {
            "post_id": TestMain.post_id,
            "account_id": TestMain.account_id,
            "right_status": 1
        }
        client = test_register_and_login.get('client')
        r = client.put(f"/posts/{data['post_id']}/right/", json=data)
        assert r.status_code == status.HTTP_205_RESET_CONTENT

    def test_delete_post(self, test_register_and_login) -> None:
        """删除帖子"""
        client = test_register_and_login.get('client')
        r = client.delete(f"/posts/{TestMain.post_id}/")
        assert r.status_code == status.HTTP_204_NO_CONTENT

    # ==================== 评论 ====================
    def test_create_comment(self, test_register_and_login) -> None:
        """创建评论

        NOTE: comment_id 由客户端用 uuid4 生成, 而生产链路是 uuid7(时间有序, 支撑游标分页),
              测试数据与真实数据的时间序语义不一致
        """
        # 评论者/主键/是否一级评论都由服务端补全, 请求体只需内容与目标对象
        data = {
            "content": "测试内容",
            "target_type": 1,
            "target_id": str(uuid.uuid4())
        }
        client = test_register_and_login.get('client')
        r = client.post('/comments/', json=data)
        assert r.status_code == status.HTTP_201_CREATED
        # 主键由服务端生成(uuid7), 与请求体里的 comment_id 无关, 必须回读响应
        TestMain.comment_id = r.json().get('comment_id')

    def test_get_comments(self, test_register_and_login) -> None:
        """评论分页(带游标 / 不带游标两种)"""
        client = test_register_and_login.get('client')
        # NOTE: 这里用 self.post_id 取的是类属性初值 '', 并非前面创建的帖子ID(应为 TestMain.post_id),
        #       因此实际请求路径形如 /comments/1//, 断言也就失去了校验意义
        r = client.get(f'/comments/1/{TestMain.post_id}/', params={'limit': 10, 'cursor': TestMain.comment_id})
        assert r.status_code == 200 and r.json().get('total') == 0, '不应该有数据'
        r = client.get(f'/comments/1/{TestMain.post_id}/', params={'limit': 10})
        assert r.status_code == 200 and r.json().get('total') == 0, '可能有数据'

    def test_delete_comment(self, test_register_and_login) -> None:
        """删除帖子"""
        client = test_register_and_login.get('client')
        r = client.delete(f"/comments/{TestMain.comment_id}/")
        assert r.status_code == status.HTTP_204_NO_CONTENT

    # ==================== 点赞 ====================
    def test_create_like(self, test_register_and_login) -> None:
        """给帖子点赞"""
        # 点赞人取令牌里的账户, 请求体只传目标对象
        data = {
            "target_id": TestMain.post_id,
            "target_type": 1
        }
        client = test_register_and_login.get('client')
        r = client.post('/likes/', json=data)
        assert r.status_code == status.HTTP_201_CREATED

    def test_delete_like(self, test_register_and_login) -> None:
        """取消点赞"""
        client = test_register_and_login.get('client')
        r = client.delete(f"/likes/{TestMain.post_id}/")
        assert r.status_code == status.HTTP_204_NO_CONTENT

    def test_get_like_count(self, test_register_and_login) -> None:
        """获取指定帖子的点赞数量"""
        client = test_register_and_login.get('client')
        r = client.get(f'/likes/{TestMain.post_id}/count/')
        assert r.status_code == 200
        assert r.json().get('is_liked') == False

    # ==================== 文件上传 ====================
    def test_upload_image(self, test_register_and_login) -> None:
        """测试图片上传

        NOTE: 原先依赖本机固定路径的图片文件, 换机器/CI 上必然失败;
              现改为运行时生成一张 8x8 的小图, 与运行环境解耦
        """
        client = test_register_and_login.get('client')
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (8, 8), (12, 34, 56)).save(buf, format="PNG")
        buf.seek(0)
        files = {'file': ('test.png', buf, 'image/png')}
        response = client.post('/upload/image/', files=files)
        assert response.status_code == status.HTTP_201_CREATED, response.text

    # ==================== 关注 ====================
    def test_create_follower(self, test_register_and_login) -> None:
        """创建关注"""
        account_id = test_register_and_login.get('account_id')
        # 被关注者主键在本仓库没有外键约束, 用合法 uuid 即可; 重点验证「重复关注返回 400」
        TestMain.followee_id = str(uuid.uuid7())
        # 关注者取令牌里的账户, 请求体只传被关注者
        data = {
            "followee_id": TestMain.followee_id
        }
        client = test_register_and_login.get('client')
        r = client.post('/follows/', json=data)
        assert r.status_code == status.HTTP_201_CREATED, r.text
        # 重复关注: 唯一索引冲突已转成 409
        r = client.post('/follows/', json=data)
        assert r.status_code == status.HTTP_409_CONFLICT

    def test_delete_follower(self, test_register_and_login) -> None:
        """删除关注"""
        client = test_register_and_login.get('client')
        # 路径里只带被关注者, 关注者取自令牌
        r = client.delete(f'/follows/{TestMain.followee_id}/')
        assert r.status_code == status.HTTP_204_NO_CONTENT

    def test_get_follow_info_by_id(self, test_register_and_login) -> None:
        """获取指定帐户的关注和正在关注数量"""
        client = test_register_and_login.get('client')
        r = client.get(f'/follows/{test_register_and_login.get("account_id")}/count/')
        assert r.status_code == 200
        assert r.json().get('is_following') == False

    def test_get_posts(self, test_register_and_login) -> None:
        """游标分页: 用「比现有帖子都新」的主键当游标, 应能取到第一页数据

        NOTE: 原写法把查询参数拼成了 'cusror', 实际测的是无游标的第一页;
              且本用例在 test_delete_post 之后执行, 库里已无该账号的帖子,
              因此这里自建一条再翻页, 使用例不依赖其它用例的执行结果
        """
        client = test_register_and_login.get('client')
        created = client.post('/posts/', json={
            "content": {},
            "post_type": 1,
            "account_id": test_register_and_login.get('account_id'),
            "from_device": 9,
            "right_status": 1,
            "location": "string",
            "is_top": False,
        })
        assert created.status_code == status.HTTP_201_CREATED, created.text

        r = client.get('/posts/', params={'limit': 10, 'cursor': str(uuid.uuid7())})
        assert r.status_code == 200, r.text
        assert r.json().get('total') > 0, '没有数据了'

    # ==================== 反馈 / 天亮即焚 ====================
    def test_submit_feedback(self, test_register_and_login):
        "测试提交反馈信息"
        client = test_register_and_login.get('client')
        payload = {
            "content": "测试内容",
            "contact": "test@alsoapp.com",
            "feedback_type": 1
        }
        r = client.post('/feedbacks/', json=payload)
        assert r.status_code == status.HTTP_201_CREATED

    def test_creat_snap(self, test_register_and_login):
        "测试发布天亮即焚"
        client = test_register_and_login.get('client')
        payload = {
            "content": {"text": "测试内容"},
            "alias_name": "test",
            "emotion": 0
        }
        r = client.post('/snaps/', json=payload)
        assert r.status_code == status.HTTP_201_CREATED
        TestMain.snap_id = r.json().get('id')

    def test_get_snaps_latest(self, test_register_and_login):
        "获取最新的十条"
        client = test_register_and_login.get('client')
        r = client.get('/snaps/latest/')
        assert r.status_code == status.HTTP_200_OK

    def test_get_snaps(self, test_register_and_login):
        "获取帖子数据"

        # NOTE: 同 test_get_posts, 'cusror' 为拼写错误, 游标实际未生效
        client = test_register_and_login.get('client')
        r = client.get('/snaps/', params={'limit': 10, 'cursor': 1})
        assert r.status_code == status.HTTP_200_OK

    def test_snaps_like(self, test_register_and_login):
        "给某条 snap 点赞(写操作, 必须是 POST)"
        client = test_register_and_login.get('client')
        r = client.post(f'/snaps/{TestMain.snap_id}/like/')
        assert r.status_code == status.HTTP_200_OK
        # 响应键随列名一起从 like 改成 like_count
        assert 'like_count' in r.json()
        assert r.json()['like_count'] >= 1

    # @pytest.mark.skip(reason="测试完成后删除测试用户")
    # def test_delete_test_user(self, session: Session) -> None:
    #     statement = delete(Account).where(Account.account_id == TestMain.account_id)
    #     session.exec(statement)
    #     session.commit()


if __name__ == '__main__':
    unittest.main()
