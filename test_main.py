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
from datetime import datetime
import random
import unittest
import uuid

import httpx
import pytz
import pytest


class TestMain:
    """测试类"""
    """测试类"""
    BASE_URL = "http://localhost:8000"
    username = ''
    passowrd = ''
    account_id = ''
    token = {}
    post_id = ''
    comment_id = ''

    @pytest.mark.run(order=1)
    def test_register(self) -> None:
        """测试用户注册"""
        data = {
            "email": f"user{random.randint(1, 20000)}@example.com",
            "password": "098f6bcd4621d373cade4e832627b4f6",
            "nick_name": "test",
            "gmt_birth": datetime.now(pytz.timezone('Asia/Shanghai')).isoformat(),
            "area_code": "CHN",
            "sex": 0,
            "avatar": "https://zos.alipayobjects.com/rmsportal/jkjgkEfvpUPVyRjUImniVslZfWPnJuuZ.png"
        }

        with httpx.Client() as client:
            r = client.post(f"{self.BASE_URL}/accounts/register/", json=data,
                            headers={"Content-Type": "application/json"})
            assert r.status_code == 200
            TestMain.username = data.get('email')
            TestMain.passowrd = data.get('password')
            TestMain.account_id = r.json().get('account_id')


    @pytest.mark.run(order=2)
    def test_authorize(self) -> None:
        # 获取请求token
        with httpx.Client() as client:
            form_data = {
                "username": TestMain.username,
                "password": TestMain.passowrd,
            }
            r = client.post(f"{self.BASE_URL}/oauth/authorize/password/", data=form_data,
                            headers={"Content-Type": "application/x-www-form-urlencoded"})
            assert r.status_code == 200
            TestMain.token = r.json()

    @pytest.mark.run(order=3)
    def test_refresh_token(self):
        """测试刷新token"""
        with httpx.Client() as client:
            r = client.get(f'{self.BASE_URL}/oauth/refresh-token/{TestMain.account_id}/refresh_token/',
                            headers={"Content-Type": "application/json", "Authorization": f"Bearer {TestMain.token.get('refresh_token')}"})
            assert r.status_code == 200
            TestMain.token['access_token'] = r.json().get('access_token')

    @pytest.mark.run(order=4)
    def test_health_check(self):
        """测试健康检查"""
        # 直接使用 httpx 发送同步 HTTP 请求
        with httpx.Client() as client:  # 使用同步客户端
            r = client.get(f"{self.BASE_URL}/health_check/")
            assert r.status_code == 200

    @pytest.mark.run(order=5)
    def test_get_account(self):
        """获取帐户信息"""
        with httpx.Client() as client:
            # ok
            r = client.get(f"{self.BASE_URL}/accounts/{TestMain.account_id}/",
                           headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}"})
            assert r.status_code == 200
            # 404
            r = client.get(f"{self.BASE_URL}/accounts/{TestMain.account_id}{random.randint(0, 9000)}/",
                           headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}"})
            assert r.status_code == 404

    @pytest.mark.run(order=6)
    def test_account_search(self):
        """搜索功能"""
        keyword = "s"
        with httpx.Client() as client:
            # ok
            r = client.get(f"{self.BASE_URL}/accounts/search/{keyword}/",
                           headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}"})
            assert r.status_code == 200

            # 404
            r = client.get(f"{self.BASE_URL}/accounts/search/{keyword}-{str(uuid.uuid4())}/",
                           headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}"})
            assert r.status_code == 404

    @pytest.mark.run(order=7)
    def test_put_account(self):
        """更新帐户信息"""
        data = {
            "nick_name": "测试test",
        }
        with httpx.Client() as client:
            response = client.put(f"{self.BASE_URL}/accounts/{TestMain.account_id}/", json=data,
                                  headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}"})
            assert response.status_code == 200

    @pytest.mark.run(order=8)
    def test_password_reset(self):
        """密码重置"""
        data = {
            "account_id": TestMain.account_id,
            "password": "stringstringstringstringstringst",
            "code": "666666"
        }
        with httpx.Client() as client:
            r = client.put(f'{self.BASE_URL}/accounts/password/reset/', json=data,
                           headers={"Content-Type": "application/json"})
            assert r.status_code == 200
            # 测试验证码不对的情况
            data['code'] = "666777"
            r = client.put(f'{self.BASE_URL}/accounts/password/reset/', json=data,
                           headers={"Content-Type": "application/json"})
            assert r.status_code == 400

    @pytest.mark.run(order=9)
    def test_password_change(self):
        """测试密码修改"""
        data = {
            "account_id": TestMain.account_id,
            "password_current": self.passowrd,
            "password_new": self.passowrd
        }
        with httpx.Client() as client:
            r = client.put(f'{self.BASE_URL}/accounts/password/change/', json=data,
                           headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}",
                                    "Content-Type": "application/json"})
            assert r.status_code == 400

    @pytest.mark.run(order=10)
    def test_create_post(self):
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
        with httpx.Client() as client:
            r = client.post(f'{self.BASE_URL}/posts/', json=data,
                            headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}",
                                     "Content-Type": "application/json"})
            assert r.status_code == 200
            TestMain.post_id = data.get('post_id')

    @pytest.mark.run(order=11)
    def test_get_posts_lasted(self):
        """获取最新帖子"""
        with httpx.Client() as client:
            r = client.get(f"{self.BASE_URL}/posts/lasted/",
                           headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}"})
            assert r.status_code == 200

    @pytest.mark.run(order=12)
    def test_update_post_right(self):
        """测试更新帖子状态"""

        data = {
            "post_id": TestMain.post_id,
            "account_id": TestMain.account_id,
            "right_status": 2
        }
        with httpx.Client() as client:
            r = client.put(f"{self.BASE_URL}/posts/{data['post_id']}/right/", json=data,
                           headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}"})
            assert 200 == r.status_code

    @pytest.mark.run(order=913)
    def test_delete_post(self):
        """删除帖子"""
        with httpx.Client() as client:
            response = client.delete(f"{self.BASE_URL}/posts/{TestMain.post_id}/",
                                     headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}"})
            assert response.status_code == 200

    @pytest.mark.run(order=14)
    def test_create_comment(self):
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
        with httpx.Client() as client:
            r = client.post(f'{self.BASE_URL}/comments/', json=data,
                            headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}",
                                     "Content-Type": "application/json"}, )
            assert r.status_code == 200
            TestMain.comment_id = data.get('comment_id')

    @pytest.mark.run(order=15)
    def test_delete_comment(self):
        """删除帖子"""
        with httpx.Client() as client:
            r = client.delete(f"{self.BASE_URL}/comments/{TestMain.comment_id}/",
                                     headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}"})
            assert r.status_code == 200

    @pytest.mark.run(order=16)
    def test_create_like(self):
        """给帖子点赞"""
        data = {
            "id": 0,
            "obj_id": TestMain.post_id,
            "account_id": TestMain.account_id,
            "gmt_created": datetime.now(pytz.timezone('Asia/Shanghai')).isoformat()
        }
        with httpx.Client() as client:
            r = client.post(f'{self.BASE_URL}/likes/', json=data,
                            headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}",
                                     "content-type": "application/json"})
            assert r.status_code == 200

    @pytest.mark.run(order=17)
    def test_delete_like(self):
        """取消点赞"""
        with httpx.Client() as client:
            r = client.delete(f"{self.BASE_URL}/likes/{TestMain.post_id}/",
                              headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}"})
            assert r.status_code == 200

    @pytest.mark.run(order=18)
    def test_upload_image(self):
        """测试图片上传"""

        with httpx.Client() as client:
            with open(r'C:\Users\liaoz\Downloads\610d9b4d-d5dd-4758-8cd3-eb029b2a39dc.jpg', 'rb') as f:
                files = {'file': ('test.jpg', f, 'image/jpeg')}
                response = client.post(f'{self.BASE_URL}/upload/image/', files=files,
                                       headers={"Authorization": f"Bearer {TestMain.token.get('access_token')}"})
                assert response.status_code == 200


if __name__ == '__main__':
    unittest.main()
