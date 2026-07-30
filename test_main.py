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
import time

import pytz
import pytest
from starlette.testclient import TestClient
from fastapi import status

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
    account_id = ''
    post_id = ''
    comment_id = ''
    md5_hash = md5()

    @pytest.fixture(scope="class", autouse=True)
    def test_register_and_login(self, client: TestClient):
        """测试用户注册"""

        passowrd = '123456'
        TestMain.md5_hash.update(passowrd.encode('utf-8'))
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
        assert r.status_code == status.HTTP_201_CREATED, f'注册失败: {r.text}'
        TestMain.account_id = r.json().get('account_id')
        username = r.json().get('username')
        account_id = r.json().get('account_id')
        email = r.json().get('email')

    #     登录逻辑
        form_data = {
            "username": username,
            "password": TestMain.md5_hash.hexdigest(),
        }
        r = client.post(f"/oauth/authorize/password/", data=form_data,
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
            "email": email,
            "refresh_token": refresh_token,
            "client": client  # 把配置好 token 的 client 也传回去
        }

    # def test_authorize(self, register_and_login) -> None:
    #     # 获取请求token
    #     # with httpx.Client() as client:
    #     form_data = {
    #         "username": TestMain.username,
    #         "password": TestMain.md5_hash.hexdigest(),
    #     }
    #     r = client.post(f"/oauth/authorize/password/", data=form_data,
    #                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    #     assert r.status_code == 200
    #     TestMain.token = r.json()
    #     # 更新token到client
    #     client.headers.update({"Authorization": f"Bearer {TestMain.token.get('access_token')}"})


    def test_refresh_token(self, test_register_and_login) -> None:
        """测试刷新token"""

        r = test_register_and_login.get('client').get(f'/oauth/refresh-token/{TestMain.account_id}/refresh_token/',
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {test_register_and_login.get('refresh_token')}"})
        assert r.status_code == 200
        access_token = r.json().get('access_token')
        test_register_and_login.get('client').headers.update({"Authorization": f"Bearer {access_token}"})

    def test_health_check(self, test_register_and_login) -> None:
        """测试健康检查"""
        # 直接使用 httpx 发送同步 HTTP 请求
        r = test_register_and_login.get('client').get(f"/health-check/")
        assert r.status_code == 200

    def test_get_account(self, test_register_and_login) -> None:
        """获取帐户信息"""
        account_id = test_register_and_login.get('account_id')
        # ok
        r = test_register_and_login.get('client').get(f"/accounts/{account_id}/")
        assert r.status_code == 200
        # 404
        r = test_register_and_login.get('client').get(f"/accounts/{account_id}{random.randint(0, 9000)}/")
        assert r.status_code == status.HTTP_404_NOT_FOUND

    def test_account_search(self, test_register_and_login) -> None:
        """搜索功能"""
        keyword = "test"
        # ok
        r = test_register_and_login.get('client').get(f"/accounts/search/{keyword}/")
        assert r.status_code == 200

        # 404
        r = test_register_and_login.get('client').get(f"/accounts/search/{keyword}-{str(uuid.uuid4())}/")
        assert r.status_code == status.HTTP_404_NOT_FOUND

    def test_put_account(self, test_register_and_login) -> None:
        """更新帐户信息"""
        data = {
            "nick_name": "测试test",
        }
        client = test_register_and_login.get('client')
        response = client.put(f"/accounts/{TestMain.account_id}/", json=data)
        assert response.status_code == 200

    def test_password_reset(self, test_register_and_login) -> None:
        """密码重置"""
        data = {
            "account_id": TestMain.account_id,
            "password": TestMain.md5_hash.hexdigest(),
            "code": "666666"
        }
        client = test_register_and_login.get('client')
        r = client.put(f'/accounts/password/reset/', json=data,
                       headers={"Content-Type": "application/json"})
        assert r.status_code == 200
        # 测试验证码不对的情况
        data['code'] = "666777"
        r = client.put(f'/accounts/password/reset/', json=data,
                       headers={"Content-Type": "application/json"})
        assert r.status_code == status.HTTP_400_BAD_REQUEST


    def test_password_change(self, test_register_and_login) -> None:
        """测试密码修改"""
        data = {
            "account_id": TestMain.account_id,
            "password_current": TestMain.md5_hash.hexdigest(),
            "password_new": TestMain.md5_hash.hexdigest()
        }
        client = test_register_and_login.get('client')
        r = client.put(f'/accounts/password/change/', json=data)
        assert r.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_post(self, test_register_and_login) -> None:
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
        client = test_register_and_login.get('client')
        r = client.post(f'/posts/', json=data)
        assert r.status_code == status.HTTP_201_CREATED
        TestMain.post_id = data.get('post_id')

    def test_get_posts_latest(self, test_register_and_login) -> None:
        """获取最新帖子"""
        client = test_register_and_login.get('client')
        r = client.get(f"/posts/latest/")
        assert r.status_code == 200

    def test_update_post_right(self, test_register_and_login) -> None:
        """测试更新帖子状态"""
        data = {
            "post_id": TestMain.post_id,
            "account_id": TestMain.account_id,
            "right_status": 2
        }
        client = test_register_and_login.get('client')
        r = client.put(f"/posts/{data['post_id']}/right/", json=data)
        assert r.status_code == status.HTTP_205_RESET_CONTENT

    def test_delete_post(self, test_register_and_login) -> None:
        """删除帖子"""
        client = test_register_and_login.get('client')
        r = client.delete(f"/posts/{TestMain.post_id}/")
        assert r.status_code == status.HTTP_204_NO_CONTENT

    def test_create_comment(self, test_register_and_login) -> None:
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
        client = test_register_and_login.get('client')
        r = client.post(f'/comments/', json=data)
        assert r.status_code == status.HTTP_201_CREATED
        TestMain.comment_id = data.get('comment_id')

    def test_delete_comment(self, test_register_and_login) -> None:
        """删除帖子"""
        client = test_register_and_login.get('client')
        r = client.delete(f"/comments/{TestMain.comment_id}/")
        assert r.status_code == status.HTTP_204_NO_CONTENT

    def test_create_like(self, test_register_and_login) -> None:
        """给帖子点赞"""
        data = {
            "id": 0,
            "obj_id": TestMain.post_id,
            "account_id": TestMain.account_id,
            "gmt_created": datetime.now(pytz.timezone('Asia/Shanghai')).isoformat()
        }
        client = test_register_and_login.get('client')
        r = client.post(f'/likes/', json=data)
        assert r.status_code == status.HTTP_201_CREATED

    def test_delete_like(self, test_register_and_login) -> None:
        """取消点赞"""
        client = test_register_and_login.get('client')
        r = client.delete(f"/likes/{TestMain.post_id}/")
        assert r.status_code == status.HTTP_204_NO_CONTENT

    def test_get_like_count(self, test_register_and_login) -> None:
        """获取指定帖子的点赞数量"""
        client = test_register_and_login.get('client')
        r = client.get(f'/likes/{self.post_id}/count/')
        assert r.status_code == 200
        assert r.json().get('is_liked') == False

    def test_upload_image(self, test_register_and_login) -> None:
        """测试图片上传"""
        client = test_register_and_login.get('client')
        with open(r'C:\Users\liaoz\Pictures\【可乐】智能云千帆行业实战：金融大模型应用探索与开发实践1915.867.png', 'rb') as f:
            files = {'file': ('test.jpg', f, 'image/jpeg')}
            response = client.post(f'/upload/image/', files=files)
            assert response.status_code == status.HTTP_201_CREATED

    def test_create_follower(self, test_register_and_login) -> None:
        """创建关注"""
        account_id = test_register_and_login.get('account_id')
        data = {
            "id": 0,
            "follower_id": account_id,
            "followee_id": f'{account_id}-test'
        }
        client = test_register_and_login.get('client')
        r = client.post(f'/follows/', json=data)
        assert r.status_code == status.HTTP_201_CREATED

        # 400
        r = client.post(f'/follows/', json=data)
        assert r.status_code == status.HTTP_400_BAD_REQUEST

    def test_delete_follower(self, test_register_and_login) -> None:
        """删除关注"""
        client = test_register_and_login.get('client')
        r = client.delete(f'/follows/{test_register_and_login.get('account_id')}/{test_register_and_login.get('account_id')}-test/')
        assert r.status_code == status.HTTP_204_NO_CONTENT

    def test_get_follow_info_by_id(self, test_register_and_login) -> None:
        """获取指定帐户的关注和正在关注数量"""
        client = test_register_and_login.get('client')
        r = client.get(f'/follows/{test_register_and_login.get('account_id')}/count/')
        assert r.status_code == 200
        assert r.json().get('is_following') == False

    def test_get_posts(self, test_register_and_login) -> None:
        """获取下页数据"""
        client = test_register_and_login.get('client')
        r = client.get(f'/posts/', params={'limit': 10, 'timestamp': int(time.time())})
        assert r.status_code == 200

    def test_get_comments(self, test_register_and_login) -> None:
        client = test_register_and_login.get('client')
        r = client.get(f'/comments/1/{self.post_id}/', params={'limit': 10, 'timestamp': int(time.time())})
        assert r.status_code == 200

    # @pytest.mark.skip(reason="测试完成后删除测试用户")
    # def test_delete_test_user(self, session: Session) -> None:
    #     statement = delete(Account).where(Account.account_id == TestMain.account_id)
    #     session.exec(statement)
    #     session.commit()

if __name__ == '__main__':
    unittest.main()
