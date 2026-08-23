# 日志系统增强设计文档

> 目标：全范围、详细、结构化日志；前端可查看；按「功能模块」分类并支持筛选。
> 状态：设计稿（未实现）

---

## 1. 现状与问题

| 项 | 现状 |
|----|------|
| 日志模块 | `src/utils/logger.py` 标准 `logging`，支持 `CHANLUN_LOG_LEVEL` 调级别，输出到 `stderr` |
| 使用分布 | `monitor_job.py` 较完整；`web/app.py` 少量；**数据层（kline_cache / baostock_fetcher / runner / trade_calendar）几乎无日志** |
| 输出去向 | 仅控制台（`StreamHandler`），**无文件落盘**，定时任务历史不可追溯 |
| 前端 | 无任何日志查看入口；失败仅 `st.error` 提示 |
| 分类 | 无统一 component 维度，难以按功能筛选 |

**核心痛点**：
1. 取数/缓存/交易日历这些关键链路看不到"命中没命中、补了多少、为什么远程"
2. 定时任务每天跑，出错只能看控制台，无法事后追溯
3. 用户无法自助排查（如"为什么显示实时查询而不是本地缓存"）

---

## 2. 设计目标

1. **全范围详细日志**：覆盖 web / runner / kline_cache / baostock / tushare / trade_calendar / monitor / 算法层，关键决策点均留痕
2. **功能分类（component）**：每条日志带 `component` 标签，前端可按模块筛选
3. **前端可查看**：新增「📋 日志」视图，支持按 component 多选 + 级别 + 关键词过滤
4. **可追溯**：日志落盘文件（按天滚动），定时任务历史可查
5. **实时性**：前端能读到最近 N 条（内存环形缓冲），无需刷新文件

---

## 3. 日志分类（component 维度）

统一 component 命名，作为每条日志的第一个结构化字段：

| component | 含义 | 典型日志 |
|-----------|------|---------|
| `WEB` | 前端交互 / 参数 / 分析触发 | 用户选择标的、点击分析、数据来源提示 |
| `RUNNER` | 编排层取数决策 | 进入 baostock/tushare 分支、频率、缺失补齐触发 |
| `KLINE_CACHE` | 本地缓存读写决策 | 命中本地 / 全量远程 / 补齐缺失段、本地条数、远程新增条数、缓存文件路径 |
| `BAOSTOCK` | Baostock 取数 | 请求 code/区间/复权、返回行数、错误码 |
| `TUSHARE` | Tushare 取数 | 同上（token 校验、接口调用） |
| `TRADE_CAL` | 交易日历 | 全量拉取 / 增量补齐、区间、写入行数、is_trading_day 命中/兜底 |
| `MONITOR` | 定时监控任务 | 启动、跳过（非交易日）、扫描标的、推送结果 |
| `CHANLUN` | 缠论算法层（分型/笔/段） | 识别起止、各阶段条数（保留现有 `print` 不改，新增 logger 等价记录） |
| `SYSTEM` | 启动/配置/异常兜底 | 配置加载、依赖缺失、未捕获异常 |

---

## 4. 后端设计

### 4.1 结构化日志格式

每条日志记录为结构化 dict（同时适配文件 JSON 与内存缓冲）：

```json
{
  "ts": "2026-08-23T14:30:05.123",
  "level": "INFO",
  "component": "KLINE_CACHE",
  "message": "命中本地缓存，未发起远程请求",
  "context": { "code": "600588.SH", "local": 397, "remote": 0, "file": "cache/baostock_600588_SH.csv" }
}
```

- `context` 为可选附加字段（不强制），便于排查
- 级别沿用标准：`DEBUG < INFO < WARNING < ERROR`

### 4.2 logger 改造（`src/utils/logger.py`）

保留现有 `get_logger` 与 stderr handler，新增：

1. **文件 Handler**：`logs/chanlun_%Y-%m-%d.log`，`TimedRotatingFileHandler`（按天滚动，保留 14 天）
   - 格式：JSON 单行（便于程序解析）或 `时间-级别-component-消息`（人类可读，二选一，建议 JSON + 可选 text）
2. **内存环形缓冲 Handler**：`RingBufferHandler`（自定义），保留最近 1000 条，供前端实时读取
   - 暴露 `get_recent_logs(limit, components, level, keyword)` 接口
3. **注入 component**：通过 `logger.bind(component=...)` 或 `extra={"component": ...}`（建议封装 `log(component, level, msg, **ctx)` 辅助函数，统一入口）

### 4.3 各模块补日志清单

| 文件 | 补点 | 级别 | component |
|------|------|------|-----------|
| `kline_cache.py` | 三分支（全量远程 / 纯本地 / 补齐段）各 1 条，含 local/remote 计数 | INFO | `KLINE_CACHE` |
| `baostock_fetcher.py` | 取数成功（行数/区间）、失败（错误码）、login/logout | INFO/ERROR | `BAOSTOCK` |
| `tushare_fetcher.py` | 同上（如启用） | INFO/ERROR | `TUSHARE` |
| `runner.py` | 进入 baostock/tushare 分支、频率、缺失补齐触发 | INFO | `RUNNER` |
| `trade_calendar.py` | 全量 / 增量补齐、写入行数、is_trading_day 命中/兜底 | INFO | `TRADE_CAL` |
| `web/app.py` | 参数选择、点击分析、数据来源提示（同步 logger）、分析失败 | INFO/ERROR | `WEB` |
| `monitor_job.py` | 已有，补 component 标签 + 补齐细节 | INFO | `MONITOR` |
| `chanlun_processor.py` | 现有 `print` 保留，新增 `logger` 等价 INFO（不删 print） | INFO | `CHANLUN` |

---

## 5. 前端设计（`web/app.py`）

### 5.1 视图切换

在侧边栏用 `st.radio`（或主区 `st.tabs`）切换两个视图：

```
🔍 分析    📋 日志
```

- 默认「分析」视图（现有功能不变）
- 「日志」视图：展示结构化日志 + 筛选控件

### 5.2 日志视图布局

```
┌─ 侧边栏筛选 ─────────────────┐
│ 组件多选 (component)          │
│   ☑ WEB  ☑ RUNNER            │
│   ☑ KLINE_CACHE  ☑ BAOSTOCK │
│   ☑ TRADE_CAL  ☑ MONITOR    │
│   ☑ CHANLUN  ☑ SYSTEM       │
│ 级别: [INFO ▼]               │
│ 关键词: [________]           │
│ 自动刷新: ☑ (每 2s)          │
│ 条数上限: [500]              │
└──────────────────────────────┘

┌─ 主区日志列表 ───────────────┐
│ 2026-08-23 14:30:05 INFO  KLINE_CACHE  命中本地缓存...  [code=600588.SH local=397 remote=0] │
│ 2026-08-23 14:30:04 INFO  RUNNER  进入 baostock 分支 freq=d ...                       │
│ ...                                                                                  │
│ (彩色级别徽章 + 可展开 context)                                                       │
└──────────────────────────────┘
```

### 5.3 实现要点

- **数据源**：调用 `logger.get_recent_logs(...)`（读内存环形缓冲），配合 `st.rerun` 或 `st.empty` + `time.sleep` 实现自动刷新
- **按 component 筛选**：多选 → 过滤 `component` 字段
- **按级别筛选**：下拉 `DEBUG/INFO/WARNING/ERROR`
- **关键词**：`message` 包含匹配
- **配色**：`ERROR` 红、`WARNING` 黄、`INFO` 蓝、`DEBUG` 灰（用 `st.markdown` + 内联样式或 `st.code`）
- **context 展开**：用 `st.expander` 显示附加字段 JSON

### 5.4 实时性说明

内存缓冲在 Web 进程内，定时任务（独立进程）的日志不会自动出现在 Web 缓冲——需读**日志文件**（`logs/chanlun_*.log`）。
两种策略：
- **A（推荐）**：前端同时支持「内存缓冲（本进程）」+「读日志文件（含 monitor 进程）」两个来源，文件来源用 `tail` 最近 N 行
- **B（简单）**：仅内存缓冲，monitor 日志不实时显示在 Web（monitor 自己有 stderr/文件）

---

## 6. 落地步骤（建议顺序）

1. **logger 增强**：加文件 handler + 环形缓冲 handler + `log(component, level, msg, **ctx)` 辅助函数（不改现有 stderr 行为）
2. **数据层补日志**：kline_cache / baostock_fetcher / runner / trade_calendar（核心痛点）
3. **入口层补日志**：web / monitor（加 component 标签）
4. **算法层补日志**：chanlun_processor（logger 等价，保留 print）
5. **前端日志视图**：侧边栏切换 + 筛选控件 + 列表展示（含文件来源读取）
6. **测试**：启动 Web，触发一次分析，在日志视图验证 component 分类与筛选生效

---

## 7. 风险与注意

- **性能**：环形缓冲上限 1000 条，文件按天滚动，无内存泄漏风险
- **敏感信息**：日志可能含 `.env` 路径、标的代码，不含 token 明文（Tushare token 不打印）
- **print 兼容**：算法层 `print` 按铁律不改，仅新增 logger 等价记录，避免重复噪音（可后续统一）
- **多进程**：Web 与 monitor 各自写同一日志文件（logging 文件 handler 进程安全，追加写），前端读文件汇总

---

## 8. 验收标准

- [ ] 全范围关键节点有 INFO 级日志，带正确 component
- [ ] 日志同时落盘 `logs/chanlun_*.log`（按天滚动）
- [ ] 前端「日志」视图可多选 component 筛选、按级别、按关键词
- [ ] 触发一次分析后，能在前端看到 `WEB → RUNNER → KLINE_CACHE → BAOSTOCK` 的完整链路
- [ ] 定时任务（monitor 进程）日志能通过前端文件来源查看
