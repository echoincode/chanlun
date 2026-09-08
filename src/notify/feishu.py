"""飞书自定义机器人 webhook 通知。

文档: https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot
若不开启签名校验，仅需 FEISHU_WEBHOOK。
若开启（机器人安全设置选了"签名校验"），需 FEISHU_SECRET，并按官方算法加 timestamp + sign。

消息形态：interactive 卡片。卡片内用 markdown 元素原生渲染 markdown
（### 标题、**加粗**、> 引用等），不再需要清洗标记，也就不会出现
原来 post 富文本残留的 ##** 之类字符。企微渠道不受影响（走原生 markdown）。
"""

import hashlib
import base64
import hmac
import logging
import re
import time

import requests

from src.notify.base import Notifier
from src.utils.logger import get_logger

# 用项目统一 get_logger（原生 logging.getLogger 无 handler，INFO 在 cmd 不可见）；
# 带 component=PUSH 标签，与前端环形缓冲/日志文件一致。
logger = logging.LoggerAdapter(get_logger(__name__), {"component": "PUSH"})


class FeishuNotifier(Notifier):
    webhook: str
    secret: str

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

    @staticmethod
    def _convert_md_for_v1(content: str) -> str:
        """将 1.0 卡片 markdown 不支持的语法转成可渲染形式。

        飞书自定义机器人 webhook 仅支持 Card JSON 1.0 内联卡片，
        i18n_*（2.0）字段不被接受，且 1.0 的 markdown 组件不支持
        # 标题 / > 引用语法（会原样显示 #、> 字符）。
        因此发送前转换：
          - #/##/### 标题行 -> **加粗** 行（卡片 header 已显示主标题，
            故正文首行标题去掉，其余层级标题转加粗）
          - > 引用行 -> 普通文本（前缀去掉，仅保留内容）
          - --- 分隔线 -> 保留（1.0 支持独立行的 ---）
        保留 **加粗**、*斜体*、列表、-、链接、emoji 等 1.0 已支持语法。
        """
        out_lines = []
        for raw in content.split("\n"):
            line = raw
            if re.match(r"^\s*#{1,6}\s+", line):
                # 标题：首行若是主标题（对应卡片 header）则跳过，其余转加粗
                if not out_lines:  # 第一行标题，跳过避免与 header 重复
                    continue
                line = re.sub(r"^\s*#{1,6}\s+", "**", line).rstrip() + "**"
                out_lines.append(line)
                continue
            if re.match(r"^\s*>\s*", line):
                line = re.sub(r"^\s*>\s*", "", line)
                out_lines.append(line)
                continue
            out_lines.append(line)
        return "\n".join(out_lines).strip("\n")

    def send(self, title: str, content: str) -> bool:
        if not self.webhook:
            return False
        # 飞书自定义机器人 webhook 仅支持 Card JSON 1.0 内联卡片
        # （i18n_* 等 2.0 字段会报 unknown property）。
        # 1.0 的 markdown 组件不支持 # 标题、> 引用语法，需在发送前转换。
        # 卡片 header 展示 title，正文用 1.0 友好的 markdown 渲染。
        timestamp, sign = self._sign()
        body_md = self._convert_md_for_v1(content)
        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "blue",
                },
                "elements": [
                    {"tag": "markdown", "content": body_md},
                ],
            },
        }
        if sign is not None:
            payload["timestamp"] = str(timestamp)
            payload["sign"] = sign
        # 调试：打印发送内容（截断避免刷屏），便于排查“一条没收到”类问题
        _preview = content if len(content) <= 500 else content[:500] + f"...(共 {len(content)} 字)"
        logger.info("[Feishu] >>> 发送内容预览(len=%d): %s", len(content), _preview)
        try:
            resp = requests.post(self.webhook, json=payload, timeout=10)
            status = resp.status_code
            try:
                data = resp.json()
            except Exception:
                data = {"raw_text": resp.text}
            ok = data.get("code") == 0
            # 打印完整返回结果（含 HTTP 状态码与平台返回体）
            logger.info(
                "[Feishu] <<< HTTP=%s 返回=%s 结果=%s",
                status, data, "成功" if ok else "失败",
            )
            return ok
        except Exception as e:  # noqa: BLE001
            logger.error("[Feishu] <<< 发送异常: %s", e)
            return False
