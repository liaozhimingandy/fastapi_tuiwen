#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： mail_service.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/8/2 18:43
    @Desc: FastAPI 全局常驻邮件服务（全局单例、启动自动初始化）

    职责: 提供 SMTP 邮件发送能力(验证码/密码重置等模板),
    init_mail_sender() 在应用启动时按环境构建全局 MailSender 单例,
    业务侧通过 send_verify_mail()/send_reset_pwd_mail() 快捷发送。

    NOTE: 生产 SMTP 授权码以明文硬编码在本文件中(smtp_password="ebvy..."),
          已随代码进入版本历史, 属安全隐患; 建议尽快作废该授权码并迁移到
          SECRET_KEY_FILE 同类的密钥文件/环境变量机制
=================================================
"""
import smtplib
from dataclasses import dataclass
from email.mime.text import MIMEText
from email.header import Header
from typing import Optional


# ==============================
# 1. 邮件模板结构体（支持变量渲染、文本/HTML双模板）
# ==============================
@dataclass
class EmailTemplate:
    """
    通用邮件模板
    支持自定义主题、纯文本内容、HTML美化内容
    支持 {变量} 动态渲染验证码、有效期等参数
    """
    subject: str
    text_template: str      # 纯文本兼容模板
    html_template: str      # 企业级HTML美化模板

    def render(self, **kwargs) -> tuple[str, str]:
        """动态渲染模板变量，返回最终文本、HTML内容"""
        text_content = self.text_template.format(**kwargs)
        html_content = self.html_template.format(**kwargs)
        return text_content, html_content


# ==============================
# 2. 邮件发送核心类（纯dataclass定义，无手写__init__）
# ==============================
@dataclass
class MailSender:
    """通用SMTP邮件发送器，支持本地测试/生产环境一键切换"""
    smtp_host: str
    smtp_port: int
    from_addr: str
    from_name: str = "系统通知"
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    use_ssl: bool = False
    timeout: int = 10

    def send(self, to_addr: str, template: EmailTemplate, **kwargs) -> bool:
        """
        统一发送入口（核心方法）
        :param to_addr: 收件人邮箱
        :param template: 邮件模板对象
        :param kwargs: 模板动态变量（code/expire等）
        :return: 发送成功/失败
        """
        # 渲染模板变量
        text_content, html_content = template.render(**kwargs)

        # 优先发送HTML模板（美观），兼容所有邮箱客户端
        msg = MIMEText(html_content, "html", "utf-8")
        from_display = Header(self.from_name, "utf-8").encode()
        msg["From"] = f"{from_display} <{self.from_addr}>"
        msg["To"] = to_addr
        msg["Subject"] = Header(template.subject, "utf-8")

        try:
            # 区分SSL/普通端口连接
            server_cls = smtplib.SMTP_SSL if self.use_ssl else smtplib.SMTP
            with server_cls(self.smtp_host, self.smtp_port, timeout=self.timeout) as server:
                # 有账号密码则登录（生产邮箱必填，本地MailDev无需）
                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.from_addr, to_addr, msg.as_string())
            print(f"✅ 邮件发送成功，收件人：{to_addr}, 内容为: {html_content}")
            return True
        except Exception as e:
            print(f"❌ 邮件发送失败: {repr(e)}")
            return False


# ==============================
# 3. 全局通用邮件模板（业界标准）
# ==============================
# 验证码邮件模板
VERIFY_CODE_TEMPLATE = EmailTemplate(
    subject="邮箱验证码 - 请勿泄露",
    text_template="""
您好！
您的本次操作验证码为：{code}
有效期:{expire}分钟
请勿将验证码告知他人，谨防诈骗。
    """.strip(),
    html_template="""
尊敬的用户：您好！您本次的操作验证码为：{code}验证码有效期:{expire} 分钟，请尽快使用。如非本人操作，请忽略本邮件。系统自动发送，请勿回复
    """.strip()
)

# 可无限扩展其他模板（重置密码、通知公告等）
RESET_PWD_TEMPLATE = EmailTemplate(
    subject="密码重置通知",
    text_template="您的密码重置验证码:{code},{expire}分钟内有效,请勿泄露。",
    html_template="""
    尊敬的用户:您好！您的密码重置验证码为:{code},有效期:{expire}分钟,请及时操作。如非本人操作,请尽快修改密码,保障账号安全。
    """.strip()
)


# ==============================
# 4. FastAPI 全局单例 + 生命周期注册（核心改造）
# ==============================
# 全局邮件发送实例（全局唯一，项目启动初始化）
global_mail_sender: Optional[MailSender] = None


def init_mail_sender(is_prod: bool = False) -> None:
    """
    初始化全局邮件服务(由 lifespan 启动阶段调用一次)
    :param is_prod: 是否生产环境，自动切换配置
    """
    global global_mail_sender

    # 生产环境配置（QQ邮箱示例，可替换为阿里/腾讯SES）
    # NOTE: 账号与授权码明文硬编码在源码中, 属敏感信息泄露风险;
    #       建议改由环境变量/密钥文件注入(可复用 core.config 的 *_FILE 加载机制)
    if is_prod:
        global_mail_sender = MailSender(
            smtp_host="smtp.qq.com",
            smtp_port=465,
            from_addr="908532252@qq.com",
            from_name="推文",
            smtp_user="908532252@qq.com",
            smtp_password="ebvyufzzodupbbgd",
            use_ssl=True
        )
    # 本地测试环境（MailDev）
    else:
        global_mail_sender = MailSender(
            smtp_host="localhost",
            smtp_port=1025,
            from_addr="no-reply@system.dev",
            from_name="系统测试服务",
            use_ssl=False
        )


# ==============================
# 5. 全局通用快捷发送方法
# ==============================
def send_verify_mail(to_email: str, code: str, expire: int = 5) -> bool:
    """全局发送验证码邮件(需先 init_mail_sender, 否则抛 RuntimeError)。"""
    if not global_mail_sender:
        raise RuntimeError("邮件服务未初始化，请在FastAPI启动事件中执行 init_mail_sender()")
    return global_mail_sender.send(
        to_addr=to_email,
        template=VERIFY_CODE_TEMPLATE,
        code=code,
        expire=expire
    )


def send_reset_pwd_mail(to_mail: str, code: str, expire: int = 10) -> bool:
    """全局发送密码重置邮件(需先 init_mail_sender)。"""
    if not global_mail_sender:
        raise RuntimeError("邮件服务未初始化，请在FastAPI启动事件中执行 init_mail_sender()")
    return global_mail_sender.send(
        to_addr=to_mail,
        template=RESET_PWD_TEMPLATE,
        code=code,
        expire=expire
    )


if __name__ == "__main__":
    import random
    mail = "dev@tw.com"
    init_mail_sender(is_prod=False)
    # 生成6位验证码
    code = "".join(random.choices("0123456789", k=6))
    # 直接调用全局邮件方法
    res = send_verify_mail(mail, code, expire=5)