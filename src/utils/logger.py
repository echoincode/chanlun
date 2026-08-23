"""缠论项目 · 统一日志模块

提供 get_logger(name) 返回标准 logging.Logger，统一格式：时间/级别/模块名。
新增（日志增强）：
  - 文件 Handler：logs/chanlun_%Y-%m-%d.log，按天滚动，保留 14 天（JSON 单行）
  - 内存环形缓冲 Handler：保留最近 1000 条，供前端实时读取
  - log(component, level, msg, **ctx)：统一入口，每条日志带 component 标签与可选 context

替换边界（算法层铁律不动）：
  ❌ 不替换：chanlun_processor.py 内业务错误 print
  ❌ 不替换：tushare_client.py 内的 print

设计要点：
  - 同一 logger name 重复调用 get_logger 不会重复添加 handler
  - 默认级别 INFO，可通过环境变量 CHANLUN_LOG_LEVEL 覆盖（DEBUG/INFO/WARNING/ERROR）
  - 不引入第三方日志库，仅用标准 logging
"""
from __future__ import annotations

import collections
import json
import logging
import os
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

# ---------------------------------------------------------------------------
# 默认格式：时间 - 级别 - 模块名 - 消息
# ---------------------------------------------------------------------------
_DEFAULT_FMT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

# 环境变量覆盖日志级别（便于调试时临时打开 DEBUG）
_LEVEL_FROM_ENV = os.environ.get("CHANLUN_LOG_LEVEL", "INFO").upper()

# 内存环形缓冲容量
_RING_CAPACITY = 1000

# 日志文件目录
_LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs",
)


class _RingBufferHandler(logging.Handler):
    """内存环形缓冲 Handler：保留最近 N 条日志记录，供前端实时读取。"""

    def __init__(self, capacity: int = _RING_CAPACITY):
        super().__init__()
        self.buffer: collections.deque = collections.deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # component 来自 record 的 extra，缺省 "SYSTEM"
            component = getattr(record, "component", "SYSTEM")
            ctx = getattr(record, "ctx", None)
            entry = {
                "ts": datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
                "level": record.levelname,
                "component": component,
                "logger": record.name,
                "message": record.getMessage(),
                "context": ctx,
            }
            self.buffer.append(entry)
        except Exception:
            self.handleError(record)


# 全局共享的环形缓冲（所有 logger 共用，便于前端统一读取）
_ring_handler = _RingBufferHandler(_RING_CAPACITY)

# 文件 Handler 懒初始化（确保日志目录存在，且仅添加一次）
_file_handler: TimedRotatingFileHandler | None = None


def _ensure_file_handler() -> TimedRotatingFileHandler:
    """懒初始化文件 Handler（按天滚动，JSON 单行格式）。"""
    global _file_handler
    if _file_handler is not None:
        return _file_handler
    os.makedirs(_LOG_DIR, exist_ok=True)
    fh = TimedRotatingFileHandler(
        os.path.join(_LOG_DIR, "chanlun.log"),
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    )
    fh.setLevel(getattr(logging, _LEVEL_FROM_ENV, logging.INFO))

    class _JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            component = getattr(record, "component", "SYSTEM")
            ctx = getattr(record, "ctx", None)
            payload = {
                "ts": datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
                "level": record.levelname,
                "component": component,
                "logger": record.name,
                "message": record.getMessage(),
                "context": ctx,
            }
            return json.dumps(payload, ensure_ascii=False)

    fh.setFormatter(_JsonFormatter())
    _file_handler = fh
    return _file_handler


def get_logger(name: str = "chanlun") -> logging.Logger:
    """获取统一格式的 Logger。

    Args:
        name: logger 名称，通常传 __name__ 或模块名。

    Returns:
        配置好 handler 与格式的 logging.Logger 实例。重复调用同一 name
        不会重复添加 handler。
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, _LEVEL_FROM_ENV, logging.INFO))

    # 避免重复添加 handler（同一 logger 多次调用只配置一次）
    if not logger.handlers:
        # 1) 控制台(stderr) —— 保留原有行为
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(getattr(logging, _LEVEL_FROM_ENV, logging.INFO))
        stderr_handler.setFormatter(logging.Formatter(_DEFAULT_FMT, datefmt=_DEFAULT_DATEFMT))
        logger.addHandler(stderr_handler)

        # 2) 文件(按天滚动 JSON) —— 所有 logger 共用同一文件 handler
        logger.addHandler(_ensure_file_handler())

        # 3) 内存环形缓冲 —— 所有 logger 共用，供前端读取
        logger.addHandler(_ring_handler)

    # 不向上层 logger 传播，避免被 root logger 重复输出
    logger.propagate = False
    return logger


def log(component: str, level: str, message: str, **ctx) -> None:
    """统一日志入口：带 component 标签与可选 context。

    Args:
        component: 功能模块标签（WEB/RUNNER/KLINE_CACHE/BAOSTOCK/TUSHARE/
                    TRADE_CAL/MONITOR/CHANLUN/SYSTEM）
        level: 级别字符串（DEBUG/INFO/WARNING/ERROR）
        message: 日志正文
        **ctx: 附加上下文字段（如 code/local/remote/file 等），可选
    """
    logger = get_logger("chanlun")
    log_level = getattr(logging, level.upper(), logging.INFO)
    # 通过 extra 把 component/ctx 传给 Handler（需在工厂外设置，避免污染其他 logger）
    logger.log(log_level, message, extra={"component": component, "ctx": ctx or None})


def get_recent_logs(
    limit: int = 500,
    components: list[str] | None = None,
    level: str = "DEBUG",
    keyword: str = "",
) -> list[dict]:
    """读取内存环形缓冲中的最近日志，支持按 component / 级别 / 关键词过滤。

    Args:
        limit: 最多返回条数
        components: 仅返回指定 component 列表（None=全部）
        level: 最低级别阈值（DEBUG/INFO/WARNING/ERROR）
        keyword: message 包含匹配（空=不筛选）

    Returns:
        日志记录 dict 列表（按时间升序）
    """
    level_rank = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
    threshold = level_rank.get(level.upper(), 10)
    entries = list(_ring_handler.buffer)

    filtered = []
    for e in entries:
        if level_rank.get(e["level"], 10) < threshold:
            continue
        if components and e["component"] not in components:
            continue
        if keyword and keyword not in e["message"]:
            continue
        filtered.append(e)

    return filtered[-limit:]


def read_log_file(
    limit: int = 500,
    components: list[str] | None = None,
    level: str = "DEBUG",
    keyword: str = "",
) -> list[dict]:
    """读取磁盘日志文件（含按天滚动备份），支持按 component / 级别 / 关键词过滤。

    用于前端「日志」视图展示跨进程（如 monitor 独立进程）产生的日志。
    自动读取当天的 chanlun.log 及其滚动备份（chanlun.log.YYYY-MM-DD）。

    Returns:
        日志记录 dict 列表（按时间升序）
    """
    level_rank = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
    threshold = level_rank.get(level.upper(), 10)

    import glob

    # 当天的日志文件 + 滚动备份（按修改时间倒序，优先最新）
    pattern = os.path.join(_LOG_DIR, "chanlun.log*")
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)

    entries: list[dict] = []
    for fpath in files:
        try:
            with open(fpath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if level_rank.get(rec.get("level", "INFO"), 10) < threshold:
                        continue
                    if components and rec.get("component") not in components:
                        continue
                    if keyword and keyword not in rec.get("message", ""):
                        continue
                    entries.append(rec)
        except OSError:
            continue

    # 按时间升序，取末尾 limit 条
    entries.sort(key=lambda x: x.get("ts", ""))
    return entries[-limit:]
