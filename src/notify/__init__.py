"""通知渠道工厂与实现。"""

from src.config import settings
from src.notify.base import Notifier
from src.notify.feishu import FeishuNotifier
from src.notify.wecom import WecomNotifier


def get_notifier(channel: str | None = None) -> Notifier | None:
    """根据配置返回通知器实例；none / 空则返回 None（调用方仅打印）。"""
    ch = (channel or settings.NOTIFY_CHANNEL).strip().lower()
    if ch == "feishu":
        return FeishuNotifier(settings.FEISHU_WEBHOOK, settings.FEISHU_SECRET)
    if ch == "wecom":
        return WecomNotifier(settings.WECOM_WEBHOOK)
    # none 或未配置：返回 None，由调用方走本地打印
    return None


def get_notifiers() -> list[Notifier]:
    """多渠道工厂：按 NOTIFY_CHANNEL 逗号分隔列表逐个实例化已配置渠道。

    仅返回 webhook 非空且受支持的 Notifier；`none` 与空项忽略。
    便于“配置几个就发几个”的批量推送（monitor_job 与 Web 按钮共用）。
    """
    result: list[Notifier] = []
    for ch in settings.NOTIFY_CHANNEL.split(","):
        ch = ch.strip().lower()
        if not ch or ch == "none":
            continue
        notifier = get_notifier(ch)
        if notifier is not None:
            result.append(notifier)
    return result


__all__ = ["Notifier", "FeishuNotifier", "WecomNotifier", "get_notifier", "get_notifiers"]
