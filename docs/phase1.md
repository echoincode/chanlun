# 缠论分析工具 · 一期项目文档

> 一期范围：数据获取 → 缠论算法 → 可视化 → Web/CLI 双入口 → 缓存与交易日历 → 日志系统 → 定时监控 → 部署与自启。
> 目标：可用、可查、可部署的缠论研学工具（A 股 / ETF 日线为主）。

---

## 一、核心功能清单

| # | 功能 | 说明 |
|---|------|------|
| 1 | 多数据源取数 | Baostock（默认，免 Token）+ Tushare（可选，需 Token）；前端下拉切换，算法层透明 |
| 2 | A 股 / ETF 支持 | 自动识别沪/深市场与 ETF（5xxxxx.SH / 159xxx.SZ），代码格式自动归一化 |
| 3 | 前复权数据 | A 股：两源均按最新交易日基准前复权，口径一致；**ETF：Baostock 不提供前复权，当前获取为未复权(除权)行情，K 线可能含除权跳空缺口**（前端已弹窗提示） |
| 4 | 本地缓存层 | 每标的 CSV 缓存，区间命中直接切片返回；缺失段增量补齐，避免全量重查 |
| 5 | 交易日历 | 本地缓存交易日期，区间查询自动收敛到交易日，规避周末/休市无谓请求 |
| 6 | K 线包含合并 | 合并相邻包含 K 线，生成缠论标准 K 线 |
| 7 | 分型识别 | 顶/底分型自动识别（多轮窗口筛选 + 关系验证） |
| 8 | 笔段分析 | 顶底交替连接，生成上升/下降笔 |
| 9 | Plotly 交互图 | 日线蜡烛 + 缠论 K 线 + 笔走势 + 分型标注 + 成交量，支持缩放/Hover/导出 HTML |
| 10 | Web 界面 | Streamlit：参数配置 + 实时分析 + 图表 + 登录守卫 |
| 11 | CLI 入口 | 交互式命令行，自动保存 HTML 图表到 `results/` |
| 12 | 数据来源提示 | 前端显示「本地缓存 / 远程查询」及**本地命中条数 + 本次新增条数** |
| 13 | 日志系统 | 结构化日志（component 分类）+ 落盘 + 内存环形缓冲；前端「📋 日志」视图可按模块/级别/关键词筛选 |
| 14 | 定时监控 | `chanlun-monitor` 常驻调度，交易日 16:30 自动跑分型监控，支持飞书/企微推送 |
| 15 | 登录守卫 | `AUTH_ENABLED` 开关 + 口令（明文或 sha256），公网部署 fail-fast 拒绝启动 |
| 16 | 启动自检 | 侧栏显示认证状态、默认数据源、Tushare 就绪情况 |
| 17 | Docker 部署 | `docker-compose` 编排 web/monitor/cli 三服务，配置经 `.env` 注入，镜像不含密钥 |
| 18 | Windows 开机自启 | `start_web.bat` + 启动文件夹/任务计划，后台拉起并弹窗提示已启动 |

---

## 二、入口与部署形态

| 形态 | 命令 / 方式 | 用途 |
|------|------------|------|
| 本地 Web | `streamlit run web/app.py --server.port 8501` | 开发调试、本机使用 |
| Windows 自启 | 双击 `start_web.bat` 或加入启动文件夹/任务计划 | 开机自动后台运行 + 弹窗 |
| CLI | `python scripts/run_tushare.py` | 命令行交互、导出 HTML |
| Docker Web | `docker compose up -d`（含 monitor） | 服务器部署，端口 8501 |
| Docker Monitor | 随 `up -d` 启动（常驻） | 每日收盘分型监控推送 |
| Docker CLI | `docker compose --profile cli up -d` | 容器内交互 shell |

---

## 三、关键模块映射

| 模块 | 路径 | 职责 |
|------|------|------|
| 数据源 | `src/data/baostock_fetcher.py` · `tushare_fetcher.py` | 取数（前复权） |
| 缓存 | `src/data/kline_cache.py` | 本地缓存 + 缺失增量补齐 |
| 交易日历 | `src/data/trade_calendar.py` | 交易日期本地缓存与查询 |
| 算法 | `src/core/chanlun_processor.py` | 合并/分型/笔段 |
| 编排 | `src/cli/runner.py` | fetch_data + analyze |
| 可视化 | `src/visual/plotly_viz.py` | Plotly 图表 |
| 日志 | `src/utils/logger.py` | 结构化日志 + 文件/内存缓冲 |
| Web | `web/app.py` · `web/auth.py` · `web/styles.py` | 界面与登录 |
| 监控 | `scripts/monitor_job.py` · `scripts/run_monitor_scheduler.sh` | 定时分型监控调度 |
| 配置 | `src/config/settings.py` · `.env` | 集中配置 |

---

## 四、一期验收状态

| 项目 | 状态 |
|------|------|
| 数据获取 / 缓存 / 交易日历 | ✅ 已完成 |
| 缠论算法（合并/分型/笔） | ✅ 已完成 |
| 交互可视化 | ✅ 已完成 |
| Web + CLI 双入口 | ✅ 已完成 |
| 数据来源条数提示 | ✅ 已完成 |
| 日志系统（后端 + 前端视图） | ✅ 已完成 |
| 定时监控 + 推送 | ✅ 已完成（需配置 `MONITOR_CODES` / 通知 webhook） |
| Docker / 开机自启 | ✅ 已完成 |

> 备注：Docker 镜像需在源码更新后 `docker compose build --no-cache` 重建，否则容器仍跑旧代码。

### 已知限制（一期）

| 项 | 说明 |
|----|------|
| ETF 未复权 | Baostock 免费源对 ETF 不提供前复权，ETF 当前获取为「未复权(除权)」行情，K 线含除权跳空缺口；A 股不受影响。后续可考虑切 Tushare 取 ETF 前复权，或缓存层做复权因子补偿 |
