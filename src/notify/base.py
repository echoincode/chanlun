"""通知渠道抽象基类。"""

from abc import ABC, abstractmethod


class Notifier(ABC):
    """通知器抽象：所有渠道实现 send(title, content) -> bool。"""

    @abstractmethod
    def send(self, title: str, content: str) -> bool:
        """发送一条通知。

        Args:
            title: 标题
            content: 纯文本/ markdown 正文（不含标题）
        Returns:
            是否发送成功
        """
        raise NotImplementedError

    @staticmethod
    def build_text(title: str, lines) -> str:
        """把标题 + 多行内容拼成字符串。"""
        if isinstance(lines, str):
            lines = [lines]
        return f"【{title}】\n" + "\n".join(lines)
