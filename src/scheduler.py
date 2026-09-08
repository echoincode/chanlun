"""收盘分型监控 - 内置定时调度器。

由环境变量驱动（见 src.config.settings.MONITOR_SCHEDULE_*），使用 APScheduler
在「Web 进程内（BackgroundScheduler）」或「作为独立进程（BlockingScheduler）」
按交易日盘后定时触发 run_monitor(force=False)。run_monitor 自身会在非交易日跳过，
因此即使触发日落在节假日也不会误推。

用法：
  - 随 Web 启动：web/app.py 导入时调用 start_background_scheduler()（幂等）。
  - 独立进程：python -m src.scheduler（前台常驻，Ctrl+C 退出）。
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import settings
from src.utils.logger import get_logger
from scripts.monitor_job import run_monitor

# 带 component=MONITOR 标签，与前端环形缓冲 / 日志文件一致。
logger = logging.LoggerAdapter(get_logger(__name__), {"component": "MONITOR"})

_started = False


def _job() -> None:
    """定时任务本体：盘后触发一次监控（非交易日 run_monitor 自行跳过）。"""
    try:
        logger.info("[scheduler] 定时任务触发，开始执行收盘监控")
        res = run_monitor(force=False)
        if not res["ran"]:
            logger.info("[scheduler] 本次未执行：%s", res.get("skipped_reason"))
            return
        logger.info(
            "[scheduler] 完成：扫描 %s 只，新分型 %s",
            res.get("scanned"), res.get("new_fractal"),
        )
    except Exception as e:  # noqa: BLE001
        logger.error("[scheduler] 定时任务异常: %s", e)


def _trigger() -> CronTrigger:
    return CronTrigger(
        hour=settings.MONITOR_SCHEDULE_HOUR,
        minute=settings.MONITOR_SCHEDULE_MINUTE,
        day_of_week=settings.MONITOR_SCHEDULE_DAYS,
    )


def start_background_scheduler() -> BackgroundScheduler | None:
    """在 Web 进程内启动后台调度（幂等，仅首次调用生效，未启用则静默跳过）。"""
    global _started
    if _started or not settings.MONITOR_SCHEDULE_ENABLED:
        return None
    sched = BackgroundScheduler()
    sched.add_job(_job, _trigger(), id="monitor_daily", replace_existing=True)
    sched.start()
    _started = True
    logger.info(
        "[scheduler] 已启动后台定时调度：每天(local) %02d:%02d（%s）触发",
        settings.MONITOR_SCHEDULE_HOUR, settings.MONITOR_SCHEDULE_MINUTE,
        settings.MONITOR_SCHEDULE_DAYS,
    )
    return sched


def run_forever() -> None:
    """作为独立进程前台运行调度器，直到进程被终止（Ctrl+C）。"""
    if not settings.MONITOR_SCHEDULE_ENABLED:
        logger.info("[scheduler] 未启用（MONITOR_SCHEDULE_ENABLED=false），退出")
        return
    sched = BlockingScheduler()
    sched.add_job(_job, _trigger(), id="monitor_daily", replace_existing=True)
    logger.info(
        "[scheduler] 前台定时调度已启动：每天(local) %02d:%02d（%s）触发，Ctrl+C 退出",
        settings.MONITOR_SCHEDULE_HOUR, settings.MONITOR_SCHEDULE_MINUTE,
        settings.MONITOR_SCHEDULE_DAYS,
    )
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown(wait=False)


if __name__ == "__main__":
    run_forever()
