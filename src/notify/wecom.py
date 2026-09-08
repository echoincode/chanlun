"""企业微信群机器人 webhook 通知。

文档: https://developer.work.weixin.qq.com/document/path/91770
支持 msgtype: text / markdown / news 等。这里用 markdown，兼容 A股涨跌色文字。
"""

import logging
import re

import requests

from src.notify.base import Notifier
from src.utils.logger import get_logger

# 用项目统一 get_logger（原生 logging.getLogger 无 handler，INFO 在 cmd 不可见）；
# 带 component=PUSH 标签，与前端环形缓冲/日志文件一致。
logger = logging.LoggerAdapter(get_logger(__name__), {"component": "PUSH"})

# 企业微信 markdown 单条上限 4096 字，留余量按 4000 切片
_WECOM_MAX_LEN = 4000


def _chunk_by_cards(content: str, max_len: int = _WECOM_MAX_LEN) -> list[str]:
    """把完整推送内容按「每张标的卡片」切分，贪心合并到多条 ≤ max_len 的消息。

    - 开头到首个 '### 📌' 之前作为 header，拼到第一片；
    - 后续每片以一张/多张卡片组成，避免单条超 4096。
    """
    idx = content.find("### 📌")
    if idx == -1:
        # 没有卡片结构，直接按长度硬切
        return [content[i: i + max_len] for i in range(0, len(content), max_len)] or [content]
    header = content[:idx].rstrip("\n")
    body = content[idx:]
    cards = re.split(r"(?=### 📌)", body)
    chunks: list[str] = []
    buf = header
    for c in cards:
        if buf and len(buf) + len(c) + 2 > max_len:
            chunks.append(buf)
            buf = c
        else:
            buf = (buf + "\n\n" + c) if buf else c
    if buf:
        chunks.append(buf)
    return chunks


class WecomNotifier(Notifier):
    def __init__(self, webhook: str):
        self.webhook = webhook

    def send(self, title: str, content: str) -> bool:
        if not self.webhook:
            return False
        # 按卡片切片，避免单条超 4096 字限制
        chunks = _chunk_by_cards(content)
        if len(chunks) == 1:
            return self._post(title, chunks[0])
        # 多片：逐条发送，全部成功才算成功
        ok_all = True
        for i, ch in enumerate(chunks):
            _t = title if i == 0 else f"{title}({i + 1}/{len(chunks)})"
            if not self._post(_t, ch):
                ok_all = False
        return ok_all

    def _post(self, title: str, content: str) -> bool:
        # 企业微信 markdown 标题用 ##，正文原样拼接；
        # 若 content 已自带 #/## 级标题（如 full_msg），则不再重复加标题
        markdown_content = (
            content if content.lstrip().startswith("#") else f"## {title}\n{content}"
        )
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": markdown_content},
        }
        # 调试：打印发送内容（截断避免刷屏），便于排查“一条没收到”类问题
        _preview = markdown_content if len(markdown_content) <= 500 else markdown_content[:500] + f"...(共 {len(markdown_content)} 字)"
        logger.info("[WeCom] >>> 发送内容预览(len=%d): %s", len(markdown_content), _preview)
        try:
            resp = requests.post(self.webhook, json=payload, timeout=10)
            status = resp.status_code
            try:
                data = resp.json()
            except Exception:
                data = {"raw_text": resp.text}
            ok = data.get("errcode") == 0
            # 打印完整返回结果（含 HTTP 状态码与平台返回体）
            logger.info(
                "[WeCom] <<< HTTP=%s 返回=%s 结果=%s",
                status, data, "成功" if ok else "失败",
            )
            return ok
        except Exception as e:  # noqa: BLE001
            logger.error("[WeCom] <<< 发送异常: %s", e)
            return False
