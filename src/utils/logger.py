"""缠论项目 · 统一日志模块（Phase 1 · Step 1-2）

提供 get_logger(name) 返回标准 logging.Logger，统一格式：时间/级别/模块名。

替换边界（本步仅定义模块，不执行替换，替换在 Phase 5/6 落实）：
  ✅ 未来可替换：app/main.py、scripts/*.py 的反馈性 print
  ❌ 不替换：chanlun_processor.py 内业务错误 print（算法层铁律不动）
  ❌ 不替换：tushare_client.py 内的 print（数据层调试输出保留原样）

设计要点：
  - 同一 logger name 重复调用 get_logger 不会重复添加 handler（避免日志重复输出）
  - 默认级别 INFO，可通过环境变量 CHANLUN_LOG_LEVEL 覆盖（DEBUG/INFO/WARNING/ERROR）
  - 不引入第三方日志库，仅用标准 logging，保持依赖最小
"""
import logging
import os
import sys

# ---------------------------------------------------------------------------
# 默认格式：时间 - 级别 - 模块名 - 消息
# ---------------------------------------------------------------------------
_DEFAULT_FMT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

# 环境变量覆盖日志级别（便于调试时临时打开 DEBUG）
_LEVEL_FROM_ENV = os.environ.get("CHANLUN_LOG_LEVEL", "INFO").upper()


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
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(getattr(logging, _LEVEL_FROM_ENV, logging.INFO))
        handler.setFormatter(logging.Formatter(_DEFAULT_FMT, datefmt=_DEFAULT_DATEFMT))
        logger.addHandler(handler)

    # 不向上层 logger 传播，避免被 root logger 重复输出
    logger.propagate = False
    return logger
