#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： test_main.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2025/2/15 21:31
    @Desc: 测试用例
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
from starlette.testclient import TestClient

from main import app

@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c

# @pytest.fixture(scope="session", autouse=True)
# def session() -> Generator[Session, None, None]:
#     with Session(create_engine("postgresql+psycopg://zhiming:zhiming@localhost:5432/tuiwen")) as session:
#         yield session

class TestMain:
    """测试类"""
    BASE_URL = "http://localhost:8000"
    username = ''
    passowrd = '123456'
    account_id = ''
    token = {}
    post_id = ''
    comment_id = ''
    md5_hash = md5()

    def test_register(self, client: TestClient) -> None:
        """测试用户注册"""
        TestMain.md5_hash.update(TestMain.passowrd.encode('utf-8'))
        data = {
            "email": f"test-user{random.randint(1, 20000)}@test-user-ap.com",
            "password": TestMain.md5_hash.hexdigest(),
            "nick_name": "test",
            "gmt_birth": datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d'),
            "area_code": "CHN",
            "sex": 0,
            "avatar": "https://zos.alipayobjects.com/rmsportal/jkjgkEfvpUPVyRjUImniVslZfWPnJuuZ.png"
        }

        # with httpx.Client() as client:
        r = client.post(f"/accounts/register/", json=data,
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 200
        TestMain.username = data.get('email')
        TestMain.passowrd = data.get('password')
        TestMain.account_id = r.json().get('account_id')


    def test_authorize(self, client: TestClient) -> None:
        # 获取请求token
        # with httpx.Client() as client:
        form_data = {
            "username": TestMain.username,
            "password": TestMain.md5_hash.hexdigest(),
        }
        r = client.post(f"/oauth/authorize/password/", data=form_data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert r.status_code == 200
        TestMain.token = r.json()
        # 更新token到client
        client.headers.update({"Authorization": f"Bearer {TestMain.token.get('access_token')}"})


    def test_refresh_token(self, client: TestClient) -> None:
        """测试刷新token"""
        r = client.get(f'/oauth/refresh-token/{TestMain.account_id}/refresh_token/',
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TestMain.token.get('refresh_token')}"})
        assert r.status_code == 200
        TestMain.token['access_token'] = r.json().get('access_token')
        client.headers.update({"Authorization": f"Bearer {TestMain.token.get('access_token')}"})

    def test_health_check(self, client: TestClient) -> None:
        """测试健康检查"""
        # 直接使用 httpx 发送同步 HTTP 请求
        r = client.get(f"/health-check/")
        assert r.status_code == 200

    def test_get_account(self, client: TestClient) -> None:
        """获取帐户信息"""
        # ok
        r = client.get(f"/accounts/{TestMain.account_id}/",
                       headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}"})
        assert r.status_code == 200
        # 404
        r = client.get(f"/accounts/{TestMain.account_id}{random.randint(0, 9000)}/")
        assert r.status_code == 404

    def test_account_search(self, client: TestClient) -> None:
        """搜索功能"""
        keyword = "s"
        # ok
        r = client.get(f"/accounts/search/{keyword}/")
        assert r.status_code == 200

        # 404
        r = client.get(f"/accounts/search/{keyword}-{str(uuid.uuid4())}/")
        assert r.status_code == 404

    def test_put_account(self, client: TestClient) -> None:
        """更新帐户信息"""
        data = {
            "nick_name": "测试test",
        }
        response = client.put(f"/accounts/{TestMain.account_id}/", json=data)
        assert response.status_code == 200

    def test_password_reset(self, client: TestClient) -> None:
        """密码重置"""
        data = {
            "account_id": TestMain.account_id,
            "password": TestMain.md5_hash.hexdigest(),
            "code": "666666"
        }
        r = client.put(f'/accounts/password/reset/', json=data,
                       headers={"Content-Type": "application/json"})
        assert r.status_code == 200
        # 测试验证码不对的情况
        data['code'] = "666777"
        r = client.put(f'/accounts/password/reset/', json=data,
                       headers={"Content-Type": "application/json"})
        assert r.status_code == 400


    def test_password_change(self, client: TestClient) -> None:
        """测试密码修改"""
        data = {
            "account_id": TestMain.account_id,
            "password_current": TestMain.md5_hash.hexdigest(),
            "password_new": TestMain.md5_hash.hexdigest()
        }
        r = client.put(f'/accounts/password/change/', json=data)
        assert r.status_code == 400

    def test_create_post(self, client: TestClient) -> None:
        """创建帖子"""
        data = {
            "post_id": str(uuid.uuid4()),
            "content": {},
            "account_id": TestMain.account_id,
            "from_ip": "",
            "from_device": 9,
            "right_status": 1,
            "location": "string",
            "is_top": False,
            "latitude": "string",
            "longitude": "string"
        }
        r = client.post(f'/posts/', json=data)
        assert r.status_code == 200
        TestMain.post_id = data.get('post_id')

    def test_get_posts_lasted(self, client: TestClient) -> None:
        """获取最新帖子"""
        r = client.get(f"/posts/lasted/")
        assert r.status_code == 200

    def test_update_post_right(self, client: TestClient) -> None:
        """测试更新帖子状态"""

        data = {
            "post_id": TestMain.post_id,
            "account_id": TestMain.account_id,
            "right_status": 2
        }
        r = client.put(f"/posts/{data['post_id']}/right/", json=data)
        assert 200 == r.status_code

    def test_delete_post(self, client: TestClient) -> None:
        """删除帖子"""
        r = client.delete(f"/posts/{TestMain.post_id}/")
        assert r.status_code == 200

    def test_create_comment(self, client: TestClient) -> None:
        """创建评论"""
        data = {
            "id": 0,
            "comment_id": str(uuid.uuid4()),
            "is_root": False,
            "parent_id": None,
            "content": "测试内容",
            "account_id": TestMain.account_id,
            "obj_id": str(uuid.uuid4()),
            "gmt_created": datetime.now(pytz.timezone('Asia/Shanghai')).isoformat(),
        }
        r = client.post(f'/comments/', json=data)
        assert r.status_code == 200
        TestMain.comment_id = data.get('comment_id')

    def test_delete_comment(self, client: TestClient) -> None:
        """删除帖子"""
        r = client.delete(f"/comments/{TestMain.comment_id}/")
        assert r.status_code == 200

    def test_create_like(self, client: TestClient) -> None:
        """给帖子点赞"""
        data = {
            "id": 0,
            "obj_id": TestMain.post_id,
            "account_id": TestMain.account_id,
            "gmt_created": datetime.now(pytz.timezone('Asia/Shanghai')).isoformat()
        }
        r = client.post(f'/likes/', json=data)
        assert r.status_code == 200

    def test_delete_like(self, client: TestClient) -> None:
        """取消点赞"""
        r = client.delete(f"/likes/{TestMain.post_id}/")
        assert r.status_code == 200

    def test_get_like_count(self, client: TestClient) -> None:
        """获取指定帖子的点赞数量"""
        r = client.get(f'/likes/{self.post_id}/count/')
        assert r.status_code == 200
        assert r.json().get('is_liked') == False

    def test_upload_image(self, client: TestClient) -> None:
        """测试图片上传"""
        with open(r'C:\Users\liaoz\Downloads\610d9b4d-d5dd-4758-8cd3-eb029b2a39dc.jpg', 'rb') as f:
            files = {'file': ('test.jpg', f, 'image/jpeg')}
            response = client.post(f'/upload/image/', files=files,
                                   headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}"})
            assert response.status_code == 200

    def test_create_follower(self, client: TestClient) -> None:
        """创建关注"""
        data = {
            "id": 0,
            "follower_id": TestMain.account_id,
            "followee_id": f'{TestMain.account_id}-test'
        }
        r = client.post(f'/follows/', json=data)
        assert r.status_code == 200

        # 400
        r = client.post(f'/follows/', json=data)
        assert r.status_code == 400

    def test_delete_follower(self, client: TestClient) -> None:
        """删除关注"""
        r = client.delete(f'/follows/{self.account_id}/{self.account_id}-test/')
        assert r.status_code == 200

    def test_get_follow_info_by_id(self, client: TestClient) -> None:
        """获取指定帐户的关注和正在关注数量"""
        r = client.get(f'/follows/{self.account_id}/count/')
        assert r.status_code == 200
        assert r.json().get('is_following') == False

    # @pytest.mark.skip(reason="测试完成后删除测试用户")
    # def test_delete_test_user(self, session: Session) -> None:
    #     statement = delete(Account).where(Account.account_id == TestMain.account_id)
    #     session.exec(statement)
    #     session.commit()

if __name__ == '__main__':
    unittest.main()
