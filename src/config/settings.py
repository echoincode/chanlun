"""缠论项目 · 集中配置常量（Phase 1 · Step 1-1）

抽离来源（数值原样搬，不触碰算法阈值）：
  - app/config.py：PAGE_CONFIG / DEFAULT_PARAMS / DATA_SOURCES / DATA_TYPES /
                   MINUTE_FREQUENCIES / MARKET_TYPES / CACHE_CONFIG / UI_CONFIG
  - app/main.py 硬编码：DEFAULT_CODE="600000" / DEFAULT_START_DATE /
                        DEFAULT_FREQUENCY="30" / DEFAULT_MINUTE_FREQ_INDEX=2
  - tushare_client.py：TUSHARE_API_URL / 超时 / 重试 / 限流（非算法阈值）

⚠️ v3 数据源切换决策（用户最终确认）：
  - tushare 完全替换 baostock + mootdx，DATA_SOURCES 只保留 tushare。
  - 原 baostock_data_fetcher.py / mootdx_data_fetcher.py 及对应 chanlun 入口弃用，
    Phase 3 仅迁移 tushare fetcher，Phase 6 仅一个 tushare CLI。
  - DEFAULT_PARAMS 的 data_source 改为 "tushare"。
  - 代码风格统一为 Tushare 格式（XXXXXX.SH / XXXXXX.SZ / XXXXXX.BJ / NNNNN.HK），
    不再使用旧版 sh.600000 风格（详见 src/utils/common.py）。

⚠️ Tushare token 走环境变量（用户决策，敏感信息不进代码库）：
  - settings.py 仅 os.environ.get('TUSHARE_TOKEN', '')，不回退硬编码。
  - 缺失时为空字符串，由 fetcher 层实例化时报错。
  - scripts/gen_golden_samples.py 的回退 demo token 仅限脚本调试，不进 settings。

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
# v3：data_source 由 "mootdx" 改为 "tushare"
# ---------------------------------------------------------------------------
DEFAULT_PARAMS = {
    "stock_code": "600588",                       # 用户默认标的
    "start_date": datetime(2025, 1, 1).date(),     # 用户默认开始时间
    "data_source": "baostock",                     # 用户默认数据源
    "data_type": "daily",
    "frequency": "30",
}

# app/main.py 硬编码补充常量
DEFAULT_CODE = "600588"                            # 用户默认标的
DEFAULT_START_DATE = datetime(2025, 1, 1).date()  # 用户默认开始时间
DEFAULT_FREQUENCY = "30"                           # app/main.py 第 269 行
DEFAULT_MINUTE_FREQ_INDEX = 2                      # app/main.py 第 274 行 selectbox index=2 → "30"

# ---------------------------------------------------------------------------
# 数据源（v3：tushare 替换 baostock + mootdx）
# ---------------------------------------------------------------------------
DATA_SOURCES = {
    "tushare": {
        "name": "Tushare",
        "description": "支持A股/ETF/指数，经私有代理取数，数据稳定（需 TUSHARE_TOKEN）",
        "supported_markets": ["A股", "ETF", "指数"],
    },
    "baostock": {
        "name": "Baostock",
        "description": "支持A股/ETF/指数/港股，免费免 token，支持分钟线",
        "supported_markets": ["A股", "ETF", "指数", "港股"],
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

# ---------------------------------------------------------------------------
# Tushare 配置（来源：tushare_client.py 的非算法魔法数字）
# ---------------------------------------------------------------------------
TUSHARE_API_URL = os.environ.get(              # Tushare API 地址（默认官方，可改用私有代理）
    "TUSHARE_API_URL", "http://api.tushare.pro"
)
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")  # 环境变量（优先读 .env），缺失为空，不回退硬编码

# 登录口令开关：true 开启登录守卫；false 关闭（任何人均可直接访问，仅本地/内网使用）。
# 取值不区分大小写，仅 "false"/"0"/"no"/"off" 视为关闭，其余一律视为开启。
_AUTH_RAW = os.environ.get("AUTH_ENABLED", "true").strip().lower()
AUTH_ENABLED = _AUTH_RAW not in ("false", "0", "no", "off")
TUSHARE_TIMEOUT = 30                          # 请求超时(秒)
TUSHARE_MAX_RETRIES = 3                       # 最大重试次数
TUSHARE_RETRY_DELAY = 1.0                     # 重试基础退避(秒)
TUSHARE_RATE_LIMIT_PER_MIN = 120              # 私有代理频率限制：120 次/分钟

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
# 监控触发时间（本地时区，HH:MM），默认收盘后 16:30
NOTIFY_TIME = os.environ.get("NOTIFY_TIME", "16:30").strip()
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
