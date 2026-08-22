"""企业微信群机器人 webhook 通知。

文档: https://developer.work.weixin.qq.com/document/path/91770
支持 msgtype: text / markdown / news 等。这里用 markdown，兼容 A股涨跌色文字。
"""

import requests

from src.notify.base import Notifier


class WecomNotifier(Notifier):
    def __init__(self, webhook: str):
        self.webhook = webhook

    def send(self, title: str, content: str) -> bool:
        if not self.webhook:
            return False
        # 企业微信 markdown 标题用 ##，正文原样拼接
        markdown_content = f"## {title}\n{content}" if not content.startswith("##") else content
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": markdown_content},
        }
        try:
            resp = requests.post(self.webhook, json=payload, timeout=10)
            data = resp.json()
            # 企业微信成功时 errcode == 0
            return data.get("errcode") == 0
        except Exception as e:  # noqa: BLE001
            print(f"[WeCom] 发送失败: {e}")
            return False
