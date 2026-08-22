"""飞书自定义机器人 webhook 通知。

文档: https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot
若不开启签名校验，仅需 FEISHU_WEBHOOK。
若开启（机器人安全设置选了"签名校验"），需 FEISHU_SECRET，并按官方算法加 timestamp + sign。
"""

import hashlib
import base64
import hmac
import time

import requests

from src.notify.base import Notifier


class FeishuNotifier(Notifier):
    def __init__(self, webhook: str, secret: str = ""):
        self.webhook = webhook
        self.secret = secret

    def _sign(self):
        timestamp = int(time.time())
        if not self.secret:
            return timestamp, None
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        sign = base64.b64encode(hmac_code).decode("utf-8")
        return timestamp, sign

    def send(self, title: str, content: str) -> bool:
        if not self.webhook:
            return False
        text = self.build_text(title, content)
        timestamp, sign = self._sign()
        payload = {
            "msg_type": "text",
            "content": {"text": text},
        }
        if sign is not None:
            payload["timestamp"] = timestamp
            payload["sign"] = sign
        try:
            resp = requests.post(self.webhook, json=payload, timeout=10)
            data = resp.json()
            # 飞书成功时 code == 0
            return data.get("code") == 0
        except Exception as e:  # noqa: BLE001
            print(f"[Feishu] 发送失败: {e}")
            return False
