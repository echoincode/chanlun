# 缠论K线分析工具 (Chanlun K-Line Analysis Tool)

基于 Python 实现的缠论技术分析系统，提供从 Tushare 数据获取到缠论算法分析（分型识别、笔段分析）的全流程支持，含 CLI 命令行和 Web 图形界面两种入口。

## 🎯 项目简介

本项目是缠论技术分析的工程化实现，核心特性：
- **单一数据源**：v4 统一使用 Tushare（支持 A股/ETF/指数），经私有代理取数稳定
- **缠论核心算法**：分型识别（顶/底分型）、笔段分析（上升/下降笔）、K线合并（包含关系处理）
- **双入口**：CLI 命令行工具（`scripts/run_tushare.py`）+ Web 图形界面（`web/app.py`）
- **交互式可视化**：Plotly 图表，支持拖拽缩放、Hover 详情、自适应宽度

## ✨ 主要特性

### 📊 数据支持范围
- **A股日线**：沪深交易所（如 600000.SH / 000001.SZ）
- **ETF 日线**：科创板/创业板 ETF（如 510300.SH / 159915.SZ）
- **指数日线**：上证/深证指数（如 000300.SH 沪深300）
- **港股**：暂不支持（需单独权限，主动提示并中断）
- **分钟线**：暂不支持（Tushare 当前仅开通日线，主动提示并中断）

### 📈 缠论核心算法
- **极值修剪**：按历史最高/最低价确定序列起点，丢弃无用区间
- **K线合并**：基于包含关系合并相邻 K 线，生成缠论 K 线
- **分型识别**：顶分型/底分型自动识别，经 11 根窗口筛选、连续分型筛选、关系验证、接近分型筛选
- **笔段分析**：按交叉原则（顶底交替）连接有效分型，形成上升/下降笔

### 🎨 可视化
- **Plotly 交互式图表**：K线图 + 成交量图双视图，支持拖拽缩放、Hover 详情
- **连续笔折线**：所有笔端点按时间顺序连成 Z 字形折线，直观展示笔段走势
- **Web 界面**：Streamlit 现代化 GUI，参数配置 + 实时分析 + 图表展示

## 📁 项目结构

```
chanlun/
├── src/                          # 源码目录（Phase 1-4 新建）
│   ├── config/
│   │   └── settings.py           # 集中配置常量（PAGE_CONFIG/CACHE_TTL 等）
│   ├── data/
│   │   ├── base_fetcher.py       # 数据获取抽象基类
│   │   └── tushare_fetcher.py    # Tushare 数据获取器（唯一数据源）
│   ├── core/
│   │   └── chanlun_processor.py  # 缠论核心算法处理器（业务算法 100% 不动）
│   ├── cli/
│   │   └── runner.py             # CLI/Web 共用计算核心（fetch_data + analyze）
│   ├── utils/
│   │   ├── common.py             # 通用工具（normalize_stock_code 等）
│   │   └── logger.py             # 统一日志模块
│   └── visual/
│       └── plotly_viz.py         # Plotly 可视化（含笔连续折线修复）
├── web/                          # Web 界面（Phase 5 新建）
│   ├── app.py                    # Streamlit 主入口
│   └── styles.py                 # CSS 样式注入
├── scripts/                      # 脚本目录（Phase 6 新建）
│   ├── run_tushare.py            # CLI 命令行入口（交互式循环）
│   └── gen_golden_samples.py     # 黄金样本生成脚本（调试用）
├── tests/                        # 测试目录
│   └── golden_samples/           # 黄金样本数据（3 组 CSV + expected.json）
├── app/                          # ⚠️ 过渡期旧入口（Phase 7 待删除）
│   ├── main.py                   # 旧 Web 入口（仍可运行）
│   └── utils.py                  # 旧工具函数
├── docs/                         # 文档目录
├── results/                      # 分析结果输出目录（HTML 图表）
├── project_backup/               # 完整代码备份（改造前冻结）
├── requirements.txt              # Python 依赖
└── .gitignore
```

## 🚀 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone <repository-url>
cd chanlun

# 创建虚拟环境
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 设置 Tushare Token（必须）
# Windows PowerShell
$env:TUSHARE_TOKEN = "your_tushare_token"
# macOS/Linux
export TUSHARE_TOKEN="your_tushare_token"
```

### 2. 方式一：CLI 命令行

```bash
python scripts/run_tushare.py
```

交互式输入参数：
```
📝 请输入分析参数（直接回车使用默认值）：
股票代码（默认 600000）: 600519.SH
开始日期（默认 2024-01-01）: 2020-01-01
结束日期（默认 2025-01-10）: 2024-12-31
```

分析完成后自动保存 HTML 图表到 `results/` 目录，并在浏览器中打开交互图表。

### 3. 方式二：Web 图形界面（推荐）

```bash
streamlit run web/app.py
```

浏览器访问 http://localhost:8501：
- 左侧边栏配置参数（股票代码、日期范围）
- 点击「🚀 开始分析」或直接修改代码自动触发
- 右侧展示分析结果摘要和交互式图表

### 4. 股票代码格式

| 市场类型 | 代码格式 | 示例 |
|---------|---------|------|
| A股（沪市） | `XXXXXX.SH` | `600000.SH` 浦发银行 |
| A股（深市） | `XXXXXX.SZ` | `000001.SZ` 平安银行 |
| ETF（沪市） | `5XXXXX.SH` | `510300.SH` 沪深300ETF |
| ETF（深市） | `159XXX.SZ` | `159915.SZ` 创业板ETF |
| 指数（上证） | `000XXX.SH` | `000300.SH` 沪深300指数 |
| 港股 | `XXXXX.HK` | ⚠️ 暂不支持，主动提示 |
| 旧前缀兼容 | `sh.XXXXXX` | 自动转换为 `XXXXXX.SH` |

## 📝 API 使用示例

```python
import os
import sys
sys.path.insert(0, ".")
os.environ["TUSHARE_TOKEN"] = "your_token"

from src.cli.runner import fetch_data, analyze
from src.visual.plotly_viz import plotly_chanlun_visualization

# 1. 获取数据
df = fetch_data("600519.SH", "2020-01-01", "2024-12-31", data_type="daily")

# 2. 缠论分析
result, summary = analyze(df)
print(f"分型: {summary.get('fractal_count')} 个 / 笔: {summary.get('segment_count')} 个")

# 3. 可视化
fig = plotly_chanlun_visualization(
    result, start_idx=0, bars_to_show=len(result),
    data_type="daily", return_fig=True, stock_code="600519.SH"
)
fig.show()
```

## 📊 输出说明

### CLI 控制台输出示例

```
🎯 缠论K线分析工具（CLI）
========================================
💡 数据源：Tushare（唯一），当前支持 A股/ETF/指数，仅日线

📝 请输入分析参数（直接回车使用默认值）：
股票代码（默认 600000）: 600519.SH
开始日期（默认 2024-01-01）: 2020-01-01
结束日期（默认 2025-01-10）: 2024-12-31

==================================================
📊 正在分析 600519.SH（日线 2020-01-01 ~ 2024-12-31）...
✅ 获取数据 1212 根K线
🎯 缠论K线: 42 根
🔺 顶分型: 3 个
🔻 底分型: 4 个
✏️ 笔: 6 个
✅ HTML文件已保存: results/600519.SH_2020-01-01_2024-12-31_daily.html
```

## 🔬 核心算法说明

### 1. 数据预处理
- **极值修剪**：根据历史最高/最低价确定序列起点，丢弃该点之前的数据
- **K线合并**：基于包含关系合并相邻 K 线，生成缠论 K 线
- **方向判断**：根据极值点类型确定初始方向（最高价在前→向下，最低价在前→向上）

### 2. 分型识别
- **顶分型**：中间 K 线高点为连续 3 根中最高
- **底分型**：中间 K 线低点为连续 3 根中最低
- **多重筛选**：11 根窗口筛选 → 连续分型筛选 → 关系验证 → 接近分型筛选（间隔≥4）

### 3. 笔段分析
- **交叉原则**：顶分型与底分型交替出现
- **上升笔**：底分型 → 顶分型
- **下降笔**：顶分型 → 底分型

## ⚙️ 配置说明

### 环境变量
| 变量名 | 必填 | 说明 |
|--------|------|------|
| `TUSHARE_TOKEN` | ✅ | Tushare API Token（私有代理 token） |
| `CHANLUN_LOG_LEVEL` | ❌ | 日志级别（默认 INFO） |

### 关键配置（`src/config/settings.py`）
| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `CACHE_TTL` | 3600 | 数据缓存时间（秒） |
| `CHART_HEIGHT` | 800 | 图表高度（像素） |
| `DEFAULT_CODE` | "600000" | 默认股票代码 |
| `DATA_SOURCES` | {"tushare"} | 唯一数据源 |

## 🐛 常见问题

### Q1: 提示 "Tushare token 缺失"
设置环境变量 `TUSHARE_TOKEN`，或在 `src/config/settings.py` 中配置。

### Q2: 港股输入显示警告
Tushare 当前仅支持 A股/ETF/指数日线，港股需单独权限。请使用 A股代码。

### Q3: 分钟线选择显示警告
Tushare 尚未开通分钟线权限，当前仅支持日线。

### Q4: Web 界面启动失败
```bash
pip install streamlit
streamlit run web/app.py
```

### Q5: 图形异常（笔不连续）
该问题已在 v4.1 修复。请使用最新版本的 `src/visual/plotly_viz.py`。

## 📚 详细文档

- [工程优化与界面美化改造方案](docs/工程优化与界面美化改造方案.md)
- [分步执行清单](docs/缠论项目工程优化-分步执行清单.md)
- [缠论核心算法文档](docs/chanlun_processor.md)
- [可视化工具文档](docs/visualization.md)

## ⚠️ 过渡期说明

- **旧入口** `app/main.py` 仍可运行（`streamlit run app/main.py`），但将在 Phase 7 后续版本废弃
- **建议**：新功能请使用 `web/app.py` 或 `scripts/run_tushare.py`

---

**注意**：本工具仅为缠论算法学习与研究的工程化尝试，不构成任何投资建议。投资有风险，入市需谨慎。
