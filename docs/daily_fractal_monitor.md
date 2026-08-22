# 每日收盘分型监控与通知方案

> 目标：每个交易日收盘后，自动判断关注标的（股票/ETF）是否**新出现顶分型 / 底分型**，并通过飞书 / 企业微信机器人推送到群，提醒人工跟进。

---

## 1. 总体架构

```
┌────────────┐   cron/系统定时任务    ┌──────────────────────┐
│ 16:30 触发  │ ───────────────────▶ │ scripts/monitor_job.py │
└────────────┘                       └──────────┬───────────┘
                                                 │
                          ┌──────────────────────┼──────────────────────┐
                          ▼                      ▼                      ▼
                  ① 读取标的清单          ② 逐个 fetch_data       ③ 本地状态比对
                  (watchlist.json)        (本地缓存优先)          (上次分型快照)
                                                 │
                                         ④ analyze() 取分型
                                                 │
                                         ⑤ 筛"新出现"分型
                                                 │
                                         ⑥ 渲染通知文本
                                                 │
                                    ┌────────────┴────────────┐
                                    ▼                         ▼
                            飞书 webhook             企业微信 webhook
```

核心原则：**只通知"新出现"的分型**，避免每天重复推送同一根已存在的分型。用本地快照文件实现去重。

---

## 2. 模块设计

### 2.1 监控标的清单（配置在 `.env`）

监控的标的**直接写在 `.env`**，用逗号分隔，便于运维改动无需动代码：

```
# 监控标的（逗号分隔，支持纯数字或带后缀，统一自动标准化）
MONITOR_CODES=600519,000858,300750,510300
```

- 由 `settings.py` 读取并解析为列表 `MONITOR_CODES`（空格自动去除）。
- 支持纯数字（如 `600519`）或带后缀（`600519.SH`），运行时经 `normalize_stock_code` 统一标准化为 Tushare 格式并去重。
- 空值或 `none` 表示不监控任何标的（脚本直接退出）。

> 为何放 `.env` 而非 `watchlist.json`：渠道、时间、标的都属于"部署配置"，统一在 `.env` 管理，改标的无需改代码/重启开发环境之外的配置。

### 2.2 取数策略：本地优先，仅补缺失日期

**不复用 `fetch_data` 的"整段拉取"语义，而是直接走 `kline_cache.load_or_fetch`**，它已实现：

- 读本地 `cache/<code>.csv`；
- 若请求区间**完全被缓存覆盖** → 直接切片返回，**不请求 Baostock**（省额度、快）；
- 若**左/右侧缺失** → 仅补缺失的那一段（如新交易日），增量写回缓存；
- 若无缓存 → 全量拉取并保存。

监控场景的取数区间：`[today - NOTIFY_LOOKBACK_DAYS, today]`。每天只可能新增最近 1 个交易日，因此**绝大多数情况命中本地缓存、仅补当天**，Baostock 请求量极小。

```python
from src.data import kline_cache
from datetime import date, timedelta

end = date.today()
start = end - timedelta(days=settings.NOTIFY_LOOKBACK_DAYS)
df = kline_cache.load_or_fetch(
    code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
    data_type="daily", frequency="d", adjustflag="2",
)
```

随后把 `df` 喂给现有 `analyze(...)`（与 Web 端同一分析管线，保证分型口径一致）。

### 2.3 主脚本 `scripts/monitor_job.py`

职责：
1. 从 `settings.MONITOR_CODES` 读取标的列表（空/`none` 直接退出）。
2. 对每只标的：用 `kline_cache.load_or_fetch` 取数（本地优先、仅补缺失）→ `analyze` 取分型。
3. 从 `summary['fractals']` 提取分型，计算**本次新分型**（`diff_new_fractals`）。
4. 读取 `state/<code>.json` 取**上次分型**（快照中 datetime 排序末位）；无快照则上次为空。
5. 组装**模板 B** 消息：每只标的展示「上次分型 → 本次分型」，**本次为空时标注"未出现新的分型"** 仍展示上次作参照。
6. 按 `get_notifiers()`（配置几个发几个）逐渠道推送模板 B 文本。
7. 更新快照文件（`state/<code>.json` 存完整 fractals）。

判定"新出现"的逻辑：

```python
def diff_new_fractals(current: list[dict], prev: list[dict]) -> list[dict]:
    prev_keys = {(f["datetime"], f["type"]) for f in prev}
    return [f for f in current if (f["datetime"], f["type"]) not in prev_keys]
```

> 说明：分型以「日期 + 类型(top/bottom)」为唯一标识。收盘后当日 K 线定型，分型才确定；次日若分型被后续 K 线破坏，旧快照里该分型仍在，但新分型会代偿，属正常缠论演化，无需额外处理。

**每只标的展示两次分型**（用户要求）：
- **上次分型**：取自上一次快照 `state/<code>.json` 中**最新一条**分型（按 datetime 排序取末位），代表"监控视角下最近一次出现的分型"。
- **本次分型**：本次 `analyze` 后 `diff_new_fractals` 得到的**新分型列表**（可能为空）。

由此三种呈现状态：
1. 本次有新分型 → 展示「上次 → 本次」对照。
2. 本次无新分型 → 该标的提示「未出现新的分型」，仍展示上次分型作为参照。
3. 标的首次纳入（无快照）→ 上次分型为空，仅展示本次（如有）。

> 快照 `state/<code>.json` 除存完整 `fractals` 外，需能快速取到"上次分型"：可直接排序取末位，无需额外字段。

> **运行时产物不入库**：`state/` 为监控运行时快照目录，已在 `.gitignore` 追加 `state/*.json`（仅保留 `state/.gitkeep` 占位），不纳入版本控制。

### 2.3 通知渠道 `src/notify/`（已落地）

抽象基类 + 两个实现，便于扩展钉钉等。

```
src/notify/
├── __init__.py    # get_notifier() / get_notifiers() 工厂，按 NOTIFY_CHANNEL 返回实例/列表
├── base.py        # Notifier 抽象：send(title, content) -> bool
├── feishu.py      # 飞书自定义机器人 webhook（含可选签名校验）
└── wecom.py       # 企业微信群机器人 webhook（markdown）
```

- `FeishuNotifier`：`msg_type=text`，成功判定 `code==0`；若 `FEISHU_SECRET` 非空则自动加 `timestamp`+`sign`（HMAC-SHA256）。
- `WecomNotifier`：`msgtype=markdown`，成功判定 `errcode==0`。
- `get_notifier(channel=None)`：`channel` 为空时读 `settings.NOTIFY_CHANNEL`；`none`/空返回 `None`（调用方仅打印）。

**多渠道并发（配置几个发几个）**：`NOTIFY_CHANNEL` 支持逗号分隔多个渠道，如 `feishu,wecom`。`get_notifiers()` 返回列表，脚本对每条消息**逐渠道推送**：

```python
def get_notifiers() -> list[Notifier]:
    chs = [c.strip() for c in settings.NOTIFY_CHANNEL.split(",") if c.strip()]
    out = []
    for ch in chs:
        if ch == "feishu" and settings.FEISHU_WEBHOOK:
            out.append(FeishuNotifier(settings.FEISHU_WEBHOOK, settings.FEISHU_SECRET))
        elif ch == "wecom" and settings.WECOM_WEBHOOK:
            out.append(WecomNotifier(settings.WECOM_WEBHOOK))
        # none / 未配置 webhook 的渠道自动跳过
    return out
```

- `NOTIFY_CHANNEL=feishu` → 只发飞书；`=wecom` → 只发企微；`=feishu,wecom` → 两个都发；`=none` 或空 → 不推送（仅打印到控制台）。
- 某渠道 webhook 为空时自动跳过，不会报错。

**连通性测试**：`scripts/notify_test.py` 内置两个真实 webhook，直接 `python scripts/notify_test.py` 即可向群推送测试消息，已验证两个渠道均可打通。

**飞书**（`feishu.py`）：POST `{FEISHU_WEBHOOK}`，`msg_type=text` 或 `interactive`（卡片）。推荐 `text` 最简单：

```python
import requests, json

def send(self, title, lines):
    payload = {
        "msg_type": "text",
        "content": {"text": f"【{title}】\n" + "\n".join(lines)}
    }
    r = requests.post(self.webhook, json=payload, timeout=10)
    return r.json().get("code") in (0, None)
```

> 飞书机器人若开启签名校验，需按官方文档加 `timestamp` + `sign`（HMAC-SHA256），配置项加 `FEISHU_SECRET`。

**企业微信**（`wecom.py`）：POST `{WECOM_WEBHOOK}`，`msgtype=markdown`：

```python
payload = {
    "msgtype": "markdown",
    "markdown": {"content": f"## {title}\n" + "\n".join(lines)}
}
```

### 2.4 状态快照 `state/<code>.json`

每只标的一份，存储最近一次分析出的完整 `fractals` 列表，供次日 diff：

```json
{
  "updated_at": "2026-08-21",
  "fractals": [
    {"datetime": "20260821", "type": "top", "high": 16.6, "low": 15.3}
  ]
}
```

---

## 2.5 前端手动触发按钮（Web 端主动调用定时任务）

除系统定时（§4）外，需在 **Web 界面（`web/app.py`）增加一个按钮**，允许用户在任意时刻**手动触发一次完整的收盘监控流程**（等价于直接运行 `scripts/monitor_job.py`），便于：

- 收盘后想立即收通知、不等 16:30 调度；
- 新标的加入 `.env` 后，想立刻验证一次是否推送正常；
- 调试通知渠道连通性（替代每次都去命令行跑脚本）。

设计要点：

1. **放置位置**：侧边栏参数区下方或主内容区顶部，独立容器（如 `st.container(border=True)` 标题「🔔 每日监控」），按钮文案 `🚀 立即执行收盘监控`。
2. **点击行为**：
   - 在按钮点击分支内，直接 `import` 并调用入口函数 `from scripts.monitor_job import run_monitor`，调用 `run_monitor(force=True)`（手动触发跳过非交易日判定）。
     > 前提：`scripts/` 需为可导入包（已加 `scripts/__init__.py`）；`app.py` 顶部已 `sys.path.insert(0, 项目根)`，故 `from scripts.monitor_job import run_monitor` 可解析。
   - 用 `with st.spinner("🔄 正在执行收盘监控...")` 包裹，避免界面卡死无反馈；
   - 执行结束后在前端展示结果摘要：`st.success(f"✅ 监控完成：扫描 {n} 只标的，{m} 只出现新分型（已推送）")`，或 `st.warning("⚠️ 监控完成，本次未检测到新分型")`；未配置标的/渠道则 `st.warning` 提示；异常则 `st.error(...)`。

3. **拉取全量标的按钮（📥 拉取全量标的）**：
   - 调用 `src.data.stock_names.load_stock_names(force_refresh=True)`，从 Baostock 拉取全市场「代码→名称」映射并缓存到 `cache/stock_names.json`；
   - 用 `st.spinner` 包裹，成功后 `st.success(f"✅ 已拉取 {n} 只标的并保存到本地")`；
   - 映射用于：① 图表标题/结果摘要展示中文名；② 监控推送模板把 `600519` 显示为「600519 贵州茅台」；
   - 非交易日 Baostock 返回空，脚本自动向前回退最多 7 个自然日取最近交易日快照（已处理 pandas 2.x 下 `get_data()` 废弃 API 问题，手动遍历 ResultSet）。
3. **日志/输出回流**：`monitor_job` 内部已有的 `print` 可通过 `contextlib.redirect_stdout` 捕获到一个 `StringIO`，执行后展示在 `st.expander("查看执行日志")` 中，便于排查（可选，非必需）。
4. **去重一致性**：手动触发与定时触发**共用同一份 `state/<code>.json` 快照**，因此手动跑过之后，当晚 16:30 定时不会再重复推送同一分型（反之亦然），行为一致。
5. **渠道联动**：直接走 `get_notifiers()`，手动触发也按 `NOTIFY_CHANNEL` 配置发几个渠道，无需额外开关。
6. **权限**：按钮同样受 `AUTH_ENABLED` 登录守卫约束（已在 `check_password()` 后渲染），无需额外处理。

> 注意：手动触发按钮**不能替代**系统定时——它只是入口复用。定时任务仍是主力，按钮是"按需立即跑"的补充手段。

---

## 3. 消息格式（两个模板，待选定）

两份模板都满足：**每只标的展示「上次分型 → 本次分型」两次记录**；本次无新分型时提示「未出现新的分型」。区别在排版密度与可读性取向。

---

### 模板 A：分组对照（推荐，信息紧凑、一眼看出变化）

按标的分组，每组两行（上次 / 本次），本次为空时明确标注。

```
【缠论收盘提醒】2026-08-21
─────────────────────
📈 600519.SH 贵州茅台
   上次: 顶分型 2026-08-15 高 1685.00
   本次: 底分型 2026-08-21 低 1620.50
📉 300750.SZ 宁德时代
   上次: 底分型 2026-08-10 低 188.00
   本次: 未出现新的分型
─────────────────────
共 2 只标的 · 1 只出现新分型
```

- 优点：对照清晰，适合标的多的群；本次无变化时也保留"上次"参照，不丢上下文。
- 缺点：纯文本，飞书/企微都通用但无彩色高亮。

---

### 模板 B：逐标的卡片（信息更全，带涨跌色与价格）

每只标的一个块，标注方向、价格、与前次间隔天数；无新分型单独成句。

```
## 缠论收盘提醒 · 2026-08-21

【600519.SH 贵州茅台】
🔺 上次顶分型: 2026-08-15 高 1685.00
🔻 本次底分型: 2026-08-21 低 1620.50（间隔 4 个交易日）

【300750.SZ 宁德时代】
🔻 上次底分型: 2026-08-10 低 188.00
⚪ 本次: 未出现新的分型

---
共监控 2 只 · 新分型 1 只
```

- 优点：markdown 卡片，企微渲染更好看；带"间隔交易日"辅助判断是否值得关注。
- 缺点：文本更长；飞书 text 模式不渲染 markdown，需切 interactive 卡片才美观（实现成本略高）。

---

**已选定：模板 B**（逐标的卡片，带涨跌色与间隔交易日）。

- 企微走 `markdown`，卡片渲染正常。
- 飞书当前 `FeishuNotifier` 用 `msg_type=text`，**不渲染 markdown**；模板 B 在飞书 text 下退化为纯文本（emoji + 换行仍在，可读但不加粗/无标题样式），不影响送达。
- 若未来要飞书也好看，可升级 `FeishuNotifier` 支持 `interactive` 卡片（另开任务，非必需）。

---

## 4. 调度方式（三选一）

| 方式 | 适用 | 命令 |
|------|------|------|
| **Windows 任务计划程序** | 本机常开 | 触发器 16:30 每日，操作 `python scripts/monitor_job.py` |
| **crontab（Linux/服务器）** | 部署到云 | `30 16 * * 1-5 cd /path/chanlun && python scripts/monitor_job.py` |
| **GitHub Actions** | 免服务器 | `schedule: cron '30 8 * * 1-5'`（UTC，注意时区） |

> A股收盘 15:00，留 30–60 分钟缓冲（数据落地、复权）再跑，建议 16:00–16:30。
> 仅工作日触发：脚本内也加「若当日非交易日则直接退出」的保护（判断 `datetime.today().weekday() < 5` 即可，严格可查交易日历）。

---

## 5. 配置项（`.env`，已落地）

```
# ===== 每日收盘分型监控 =====
# 监控标的（逗号分隔，支持纯数字或带后缀，统一自动标准化）
MONITOR_CODES=600519,000858,300750,510300
# 通知渠道（逗号分隔，可配置多个：feishu / wecom / none；none 仅打印不推送）
NOTIFY_CHANNEL=feishu,wecom
# 飞书自定义机器人 webhook（及可选签名密钥，开启签名校验时填）
FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxxx
FEISHU_SECRET=
# 企业微信群机器人 webhook
WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx
# 监控触发时间（本地时区 HH:MM，建议收盘后 16:30）
NOTIFY_TIME=16:30
# 监控回看天数（取数区间长度，保证分型识别充分）
NOTIFY_LOOKBACK_DAYS=120
```

读取位置：`src/config/settings.py` 统一加载：
- `MONITOR_CODES` → 列表（支持纯数字/带后缀，经 `normalize_stock_code` 标准化去重），空/`none` 不监控。
- `NOTIFY_CHANNEL` / `FEISHU_WEBHOOK` / `FEISHU_SECRET` / `WECOM_WEBHOOK` / `NOTIFY_TIME` / `NOTIFY_LOOKBACK_DAYS`。

`src/notify/__init__.py` 的 `get_notifiers()` 按 `NOTIFY_CHANNEL`（逗号分隔）返回**多个**通知器，配置几个发几个；`none`/空返回空列表，上层仅打印。`NOTIFY_TIME` 与 `NOTIFY_LOOKBACK_DAYS` 供调度与取数区间使用（见 §4 / §2.2）。

---

## 6. 与现有代码的复用

| 需求 | 复用现有 |
|------|---------|
| 取 K 线 | `src.data.kline_cache.load_or_fetch`（本地优先、仅补缺失段；内部调用 `BaostockClient`，与 §2.2 一致） |
| 分型识别 | `src.cli.runner.analyze(df)` → `(result_df, summary)`，分型在 `summary['fractals']`（单参 DataFrame） |
| 缓存 | `src/data/kline_cache.py`（区间命中免请求） |
| 快照 | `state/<code>.json`（运行时产物，已加入 `.gitignore`，不纳入版本控制） |
| 配置 | `src/config/settings.py`（读 `.env`） |
| 入口复用 | `scripts/monitor_job.run_monitor(force=False)` 同时供命令行与 Web 按钮调用 |

**零新依赖**：`requests` 已在 `requirements.txt`（若没有则补一行）。

---

## 7. 任务清单（实施追踪）

> 状态：✅ 已完成 ｜ ⬜ 待做 ｜ 🔶 进行中
> 本次（2026-08-22）：实现核心功能（`MONITOR_CODES`、`monitor_job.py`、`state/` 快照、Web 按钮），并同步修订文档。

### 7.1 已完成
| # | 任务 | 产出 |
|---|------|------|
| 1 | 通知模块 base/feishu/wecom + `get_notifiers()` 多渠道 | `src/notify/` |
| 2 | 飞书 / 企微 webhook 连通性验证 | `scripts/notify_test.py`（两渠道均 ✅ 打通） |
| 3 | `settings.py` 通知配置读取（渠道/webhook/时间/回看） | `NOTIFY_CHANNEL` 等已落地 |
| 4 | `.env` 通知渠道 + 真实 webhook | 已填 `feishu` + `wecom` |
| 5 | 方案文档：取数本地优先、标的放 `.env`、多渠道并发 | 本文档 §2/§5 |
| 6 | **消息模板选定：模板 B**（双分型对照 + 未出现提示） | 本文档 §3 |
| 7 | `MONITOR_CODES` 解析（`settings.py`）+ `.env` 示例 | 2026-08-22 落地 |
| 8 | 核心 `scripts/monitor_job.py`（取数/分析/快照/模板B/去重/非交易日） | 2026-08-22 落地 |
| 9 | `state/` 快照目录 + `.gitignore` 忽略 `state/*.json` | 2026-08-22 落地 |
| 10 | Web 端「立即执行收盘监控」按钮（`web/app.py`） | 2026-08-22 落地，复用 `run_monitor(force=True)` |

### 7.2 待做（下一步实施 `monitor_job.py`）

> 更新（2026-08-22）：#1~#7、#9、#10 已全部落地实现；仅 **#8 调度配置** 仍待用户在部署环境操作（Windows 任务计划 / crontab / Actions）。

| # | 任务 | 说明 | 状态 |
|---|------|------|------|
| 1 | `settings.py` 加 `MONITOR_CODES` 解析 | 逗号分隔→列表，空→空列表 | ✅ 已落地 |
| 2 | `.env` 填 `MONITOR_CODES` | 监控标的清单 | ✅ 示例已写入 `.env.example` |
| 3 | 建 `scripts/monitor_job.py`（核心） | 见下方 §7.3 职责清单 | ✅ 已落地 |
| 4 | 快照读写 `state/<code>.json` | 存 `last_fractal`，取作"上次分型" | ✅ 已落地 |
| 5 | 模板 B 消息组装函数 | 上次→本次对照；本次空→"未出现新的分型" | ✅ 已落地 |
| 6 | 非交易日自动退出 | `weekday() < 5`，可选查交易日历 | ✅ 已落地 |
| 7 | 本地验证 `python scripts/monitor_job.py` | 先 `NOTIFY_CHANNEL=none` 看输出 | ✅ 已验证 |
| 8 | 配调度（任务计划/crontab/Actions，16:30 后） | 本文档 §4 | ⬜ 待用户部署 |
| 9 | `monitor_job` 暴露可复用入口 `run_monitor()` | 供前端按钮 import 调用 | ✅ 已落地 |
| 10 | Web 端（`web/app.py`）加「立即执行收盘监控」按钮 | 复用 §2.5 设计 | ✅ 已落地 |

### 7.3 `monitor_job.py` 职责清单（落地时对照）
1. 读 `settings.MONITOR_CODES`；空则退出。
2. 读 `settings.NOTIFY_TIME` / `NOTIFY_LOOKBACK_DAYS`（取数区间用）。
3. 非交易日（`weekday>=5`）直接退出。
4. 逐标的：
   a. `kline_cache.load_or_fetch(code, start, end)`（本地优先、仅补缺失）。
   b. `analyze(df)` → `(result_df, summary)`，`summary['fractals']` 为分型列表（单参 DataFrame，与 web 端一致）。
   c. `diff_new_fractals` 算**本次新分型**。
   d. 读 `state/<code>.json` 取**上次分型**（末位）；无快照则上次为空。
   e. 按**模板 B** 组装该标的文本块。
   f. 写回快照（完整 fractals）。
5. 聚合全部标的文本块 → `get_notifiers()` 逐渠道推送（配置几个发几个）。
6. `NOTIFY_CHANNEL=none`/空 → 仅 `print`，不推送。

### 7.4 可选增强（非阻塞）
- `--init-only`：仅建快照不推送（避免首次全推）。
- 飞书 `interactive` 卡片：让模板 B 在飞书也好看（当前 text 退化可读）。
- webhook 失败 1–2 次重试；退出码非 0 便于调度器告警。

---

## 8. 边界与注意

- **分型滞后性**：分型需在右侧第 2 根 K 线确认后才出现（缠论包含关系规则），所以"当日收盘出现分型"实际是当日及前两日定型的结果，符合预期。
- **重复推送**：靠 `state/<code>.json` 快照去重；若手动删快照会重新全推。
- **网络/限流**：Baostock 有频率限制，多标的串行请求、必要时 `time.sleep`。飞书/企微 webhook 有每秒限流，单条消息聚合所有标的即可。
- **失败重试**：webhook 失败可加 1–2 次重试；脚本退出码非 0 便于调度器告警。
- **时区**：服务器 UTC 时需换算（16:30 CST = 08:30 UTC）。
