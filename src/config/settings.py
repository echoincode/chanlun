"""缠论项目 · 集中配置常量（Phase 1 · Step 1-1）

抽离来源（数值原样搬，不触碰算法阈值）：
  - app/config.py：PAGE_CONFIG / DEFAULT_PARAMS / DATA_SOURCES / DATA_TYPES /
                   MINUTE_FREQUENCIES / MARKET_TYPES / CACHE_CONFIG / UI_CONFIG
  - app/main.py 硬编码：DEFAULT_CODE="600000" / DEFAULT_START_DATE /
                        DEFAULT_FREQUENCY="30" / DEFAULT_MINUTE_FREQ_INDEX=2

⚠️ 数据源切换决策（用户最终确认）：
  - 全项目唯一数据源为本地 stockdb 服务，DATA_SOURCES 只保留 stockdb。
  - 原 tushare / baostock / mootdx 数据源及其 CLI 入口已全部移除。
  - DEFAULT_PARAMS 的 data_source 固定为 "stockdb"。
  - 代码风格统一为 XXXXXX.SH / XXXXXX.SZ / XXXXXX.BJ 格式，
    不再使用旧版 sh.600000 风格（详见 src/utils/common.py）。

⚠️ 算法层阈值（window=4、min_gap=4、merge_klines 规则等）位于
   chanlun_processor.py 内部，保持原位，不抽离到本文件。
"""
import os
from datetime import datetime

# 启动时从项目根目录的 .env 加载环境变量（容器/本地统一来源）。
# 已存在于真实环境（如 docker-compose 注入）的变量不会被覆盖。
try:
    from dotenv import load_dotenv
    # 优先项目根目录（Settings 被导入时 cwd 即项目根）；找不到则静默跳过
    load_dotenv(override=False)
except Exception:
    # python-dotenv 未安装时不影响从真实环境变量读取
    pass


# ---------------------------------------------------------------------------
# 页面配置（来源：app/config.py，原样）
# ---------------------------------------------------------------------------
PAGE_CONFIG = {
    "page_title": "缠论K线分析工具",
    "page_icon": "📊",
    "layout": "wide",
    "initial_sidebar_state": "expanded",
}

# ---------------------------------------------------------------------------
# 默认参数（来源：app/config.py DEFAULT_PARAMS + app/main.py 硬编码）
# data_source 固定为 "stockdb"（本地 stockdb 服务，唯一数据源）
# ---------------------------------------------------------------------------
DEFAULT_PARAMS = {
    "stock_code": "600588",                       # 用户默认标的
    "start_date": datetime(2025, 1, 1).date(),     # 用户默认开始时间
    "data_source": "stockdb",                       # 用户默认数据源
    "data_type": "daily",
    "frequency": "30",
}

# app/main.py 硬编码补充常量
DEFAULT_CODE = "600588"                            # 用户默认标的
DEFAULT_START_DATE = datetime(2025, 1, 1).date()  # 用户默认开始时间
DEFAULT_FREQUENCY = "30"                           # app/main.py 第 269 行
DEFAULT_MINUTE_FREQ_INDEX = 2                      # app/main.py 第 274 行 selectbox index=2 → "30"

# ---------------------------------------------------------------------------
# 数据源（唯一：本地 stockdb 服务）
# ---------------------------------------------------------------------------
DATA_SOURCES = {
    "stockdb": {
        "name": "StockDB",
        "description": "本地 stockdb 服务（D:\\stockdb\\stockdb.exe），免 token、全本地、低延迟，支持前/后复权",
        "supported_markets": ["A股", "ETF", "指数"],
    },
}

# ---------------------------------------------------------------------------
# 数据类型 / 分钟周期 / 市场类型映射（来源：app/config.py，原样）
# ---------------------------------------------------------------------------
DATA_TYPES = {
    "daily": "日线",
    "minute": "分钟线",
}

MINUTE_FREQUENCIES = ["5", "15", "30", "60"]

MARKET_TYPES = {
    "stock": "A股",
    "etf": "ETF",
    "index": "指数",
    "hk": "港股",
}

# ---------------------------------------------------------------------------
# 缓存配置（来源：app/config.py CACHE_CONFIG，原样：ttl=3600 / max_entries=100）
# ---------------------------------------------------------------------------
CACHE_CONFIG = {
    "ttl": 3600,        # 缓存时间(秒)
    "max_entries": 100,  # 最大缓存条目数
}

CACHE_TTL = CACHE_CONFIG["ttl"]              # 便捷别名（抽离清单要求）
MAX_CACHE_ENTRIES = CACHE_CONFIG["max_entries"]

# ---------------------------------------------------------------------------
# UI 配置（来源：app/config.py UI_CONFIG，原样：chart_height=800）
# ---------------------------------------------------------------------------
UI_CONFIG = {
    "chart_height": 800,
    "chart_width": "100%",
    "button_width": "100%",
}

CHART_HEIGHT = UI_CONFIG["chart_height"]      # 便捷别名（抽离清单要求）

# 登录口令开关：true 开启登录守卫；false 关闭（任何人均可直接访问，仅本地/内网使用）。
# 取值不区分大小写，仅 "false"/"0"/"no"/"off" 视为关闭，其余一律视为开启。
_AUTH_RAW = os.environ.get("AUTH_ENABLED", "true").strip().lower()
AUTH_ENABLED = _AUTH_RAW not in ("false", "0", "no", "off")

# 输出目录（app/main.py 使用的 results / cache 路径）
RESULTS_DIR = "results"
CACHE_DIR = "cache"

# 每日收盘分型监控 - 通知渠道配置
# NOTIFY_CHANNEL: 通知渠道，可选 feishu / wecom / none（none 仅打印不推送，用于本地调试）
NOTIFY_CHANNEL = os.environ.get("NOTIFY_CHANNEL", "none").strip().lower()
# 飞书自定义机器人 webhook 及可选签名密钥
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "")
FEISHU_SECRET = os.environ.get("FEISHU_SECRET", "")  # 开启签名校验时填写
# 企业微信群机器人 webhook
WECOM_WEBHOOK = os.environ.get("WECOM_WEBHOOK", "")
# 监控回看天数（取数区间长度，保证分型识别充分）
NOTIFY_LOOKBACK_DAYS = int(os.environ.get("NOTIFY_LOOKBACK_DAYS", "120"))
# 监控标的：逗号分隔的标准化代码列表（如 "600519.SH,000001.SZ,513050.SH"）
# 留空表示不监控任何标的（脚本退出，Web 按钮提示配置）。
_MONITOR_CODES_RAW = os.environ.get("MONITOR_CODES", "")
MONITOR_CODES = (
    [c.strip() for c in _MONITOR_CODES_RAW.split(",") if c.strip()]
    if _MONITOR_CODES_RAW
    else []
)

# ---------------------------------------------------------------------------
# AI 研判（OpenAI 兼容）配置
# 凭据（AI_BASE_URL / AI_API_KEY / AI_MODEL）仅从环境变量读取，绝不硬编码。
# 默认 AI_ENABLED=false：未配置时单标的「AI 深度分析」悬浮按钮仅给出配置指引，
# 不影响既有分析 / 绘图 / 收盘监控。
# ---------------------------------------------------------------------------
AI_ENABLED = os.environ.get("AI_ENABLED", "false").strip().lower() in ("true", "1", "yes", "on")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "").strip()          # OpenAI 兼容端点，如 .../v1
AI_MODEL = os.environ.get("AI_MODEL", "").strip()
AI_API_KEY = os.environ.get("AI_API_KEY", "").strip()            # 仅环境变量，绝不入库/不打印
AI_TIMEOUT = int(os.environ.get("AI_TIMEOUT", "60"))
AI_MAX_TOKENS = int(os.environ.get("AI_MAX_TOKENS", "4000"))
AI_MAX_RETRY = int(os.environ.get("AI_MAX_RETRY", "1"))
AI_KLINE_WINDOW = int(os.environ.get("AI_KLINE_WINDOW", "30"))   # 以最新分型为起点的 K 线窗口根数（含分型本身及之后的 K 线与成交量，硬上限 60）
# （不做基本面研判，无 AI_INCLUDE_FUNDAMENTALS 开关）
# （资金流无开关：个股日资金流默认必须附带，见 src/ai/review.py build_single_payload）
