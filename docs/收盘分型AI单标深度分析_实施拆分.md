# 收盘分型 AI 单标的深度分析 · 实施拆分（一步一验证）

> 配套方案：`docs/收盘分型AI单标的深度分析方案.md`（2026-09-08 版）。
> 本文件只拆分**该单标的方案自身**的改动，采用「一步一验证」结构：每步设验证闸门，未全绿不进下一步。
>
> **范围声明**：`call_ai` / `parse_review` / `AI_*` 配置 / `openai` 依赖 / `build_ai_payload` 均由
> 《收盘分型 AI 研判方案》提供（单标的方案 §2、§6、§8 明确标注「依赖主方案」）。**本任务不实现这些项**，
> 仅将其列为「外部前置依赖」并给出存在性校验；若缺失，本任务在此处阻塞，待主方案落地。
>
> **修订记录**：2026-09-08 初版（单标的方案专项拆分）。

---

## 0. 拆分原则与外部前置依赖

**原则**
1. **一步一验证**：每步结尾有「验证闸门」，未全绿不进入下一步。
2. **可独立回滚**：每步只动指定文件，失败即 `git checkout` 该文件。
3. **不改其他功能**：不触碰 `runner.analyze` / `cached_analysis` 取数 / `monitor_job` / 绘图 / 批量推送。
4. **AI 真实调用可离线验证**：用 `monkeypatch` 注入假 `call_ai`，不依赖网络与 key。

**依赖顺序**
```
[外部前置] AI 基础（主方案提供，本任务不实现）
        │
        ├─> Phase 1  build_single_payload + 单测
        ├─> Phase 2  FAB 样式（可与 Phase 1 并行）
        │
        └─> Phase 3  app.py 集成（须 1/2 全绿）
                  │
                  └─> Phase 4  README（可全程并行，最后收尾）
```

### 外部前置依赖 · 存在性校验闸门
本任务执行前，必须已具备（来自主方案，不在此实现）：
- `src/config/settings.py` 已含 `AI_ENABLED`/`AI_BASE_URL`/`AI_MODEL`/`AI_API_KEY`/`AI_TIMEOUT`/`AI_MAX_TOKENS`/`AI_MAX_RETRY`/`AI_KLINE_WINDOW`（**无** `AI_INCLUDE_FUNDAMENTALS`，不做基本面）；
- `requirements.txt` 已含 `openai`；
- `src/ai/review.py` 已实现 `call_ai`、`parse_review`（及 `build_ai_payload`）。

**闸门命令**：
```bash
python -c "from src.config.settings import AI_ENABLED,AI_BASE_URL,AI_MODEL,AI_API_KEY,AI_TIMEOUT,AI_MAX_TOKENS,AI_MAX_RETRY,AI_KLINE_WINDOW; from src.ai.review import call_ai, parse_review; print('AI base ready')"
python -c "import openai; print('openai', openai.__version__)"
```
两者均无报错 → 前置通过，进入 Phase 1。否则**阻塞**，转主方案先落地。

---

## Phase 1 · 单标的 payload 组装（方案 §3 / §5 #1）

### Step 1.1 · 新增 `build_single_payload`
- **目标**：按方案 §3 从 `result`/`summary` 组装单标的 payload（不指定锚点、传分型序列、`meta` 带周期）。
- **改动文件**：`src/ai/review.py`（新增函数，**复用**既有 `build_ai_payload` 的切片工具，不另写逻辑）。
- **实现要点**：严格对齐方案 §3.1 字段表与 §3.2 签名：
  ```python
  def build_single_payload(kline_tail, summary, stock_code, stock_name,
                           data_type="daily", frequency=None) -> dict:
  ```
  - `recent_fractals = summary["fractals"][-8:]`、`recent_segments = summary["segments"][-5:]`；
  - `kline_window` 由调用方传入的 `kline_tail`（已截 `AI_KLINE_WINDOW`，硬上限 60）；
  - `last_close = kline_tail.iloc[-1]["close"]`；
  - `meta.data_type`/`meta.frequency` 写入；`meta.truncated` 恒 `false`；`signals` 恒 1 条；
  - 价格直接取 `segment.start_price`/`end_price`；`date` 由 `datetime` 归一（日线 `20260713` / 分钟线 `20260713140000`）；
  - **边界**：`summary.fractals` 为空 → 返回 `{}`；仅 1 个分型 → 正常返回。
- **验证闸门**：`python -c "from src.ai.review import build_single_payload; print('import ok')"` 无报错。
- **完成标准**：函数可 import；签名与方案 §3.2 一致。

### Step 1.2 · 单测 `test_payload.py`
- **目标**：固化切片口径与边界（方案 §5 #1、§7 #7）。
- **改动文件**：新建 `src/ai/tests/test_payload.py`（及 `src/ai/tests/__init__.py`，沿用项目 pytest 约定）。
- **实现要点**用例：
  1. `recent_fractals` 截断 ≤ 8、`recent_segments` ≤ 5、`kline_window` 行数 = `AI_KLINE_WINDOW`（≤60）；
  2. `summary.fractals` 为空 → 返回 `{}`；
  3. 仅 1 个分型 → 正常返回（序列长度 1）；
  4. `meta.data_type`/`meta.frequency` 正确写入（日线 vs 分钟线）。
- **验证闸门**：
  ```bash
  python -m pytest src/ai/tests/test_payload.py -v
  ```
  全绿 → 通过。
- **完成标准**：切片口径符合 §3；Phase 1 完成，可进 Phase 3（与 Phase 2 并行亦可）。

---

## Phase 2 · 悬浮按钮样式（方案 §4.2 / §5 #2，可与 Phase 1 并行）

### Step 2.1 · `inject_styles()` 追加 `.ai-fab` CSS
- **目标**：FAB 右下圆角浮动样式（避让 Streamlit 状态控件）。
- **改动文件**：`web/styles.py` 的 `inject_styles()` 内 `<style>` 追加（方案 §4.2 原样 CSS）。
- **实现要点**：`.ai-fab > button { position: fixed; right:28px; bottom:64px; z-index:999; ... }`，`.ai-fab > button:hover` 提亮。
- **验证闸门**：`python -c "import web.styles; web.styles.inject_styles(); print('styles ok')"` 无异常。
- **完成标准**：CSS 注入函数可调用；`bottom:64px` 错开状态控件。

### Step 2.2 · 新增 `inject_ai_fab_js()`
- **目标**：按按钮唯一 label 加浮动类；**每次 rerun 必须调用**（方案 §4.2 星标说明）。
- **改动文件**：`web/styles.py` 新增函数，内部 `st.components.v1.html(JS, height=0, width=0)`（JS 见方案 §4.2，按 `innerText.includes("AI 深度分析")` 定位加类）。
- **实现要点**：函数体仅做 DOM 定位；JS 不可用时自然回退为普通按钮（功能不丢）。
- **验证闸门**：
  ```bash
  python -c "import web.styles; assert hasattr(web.styles,'inject_ai_fab_js'); web.styles.inject_ai_fab_js(); print('fab js ok')"
  ```
  无异常且函数存在 → 通过。
- **完成标准**：`inject_ai_fab_js()` 存在且被 `_render_ai_fab()` 每次 rerun 调用（Phase 3 落实调用）。

### Step 2.3 · 页面样式人工验证
- **目标**：确认浮动效果与回退（方案 §5 #2）。
- **验证闸门**：
  ```bash
  streamlit run web/app.py
  ```
  打开 `http://localhost:8501`：① 右下出现圆角悬浮按钮且与状态控件不重叠；② 临时注释 `inject_ai_fab_js()` 调用 → 按钮回退为普通按钮、功能不丢。
- **完成标准**：浮动正常、回退可用；Phase 2 完成。

---

## Phase 3 · 页面集成（须 Phase 1、Phase 2 全绿后；方案 §4.1/§4.3/§5 #3）

### Step 3.1 · 分析成功分支无条件写 `ai_ctx`
- **目标**：最近一次分析数据落 `session_state`，供 FAB 复用（rerun 安全，方案 §4.1）。
- **改动文件**：`web/app.py` 分析成功分支末尾（`app.py:502` 之后），**无条件**写入方案 §4.1 的 `ai_ctx` 字典（`summary`/`kline_tail=result.tail(AI_KLINE_WINDOW)`/`stock_code`/`stock_name`/`data_type`/`frequency`/`start_date`/`end_date`）。
- **实现要点**：赋值不依赖任何条件（首次分析时尚无 `ai_ctx`）；顶部 `from src.config import settings`。
- **验证闸门**：`python -c "import web.app"` 无语法错误；启动页面分析一只股无报错（Step 3.3 一并验）。
- **完成标准**：分析后 `st.session_state.ai_ctx` 存在且含尾窗切片与周期字段。

### Step 3.2 · `main()` 渲染 FAB 与结果
- **目标**：FAB 常驻、引导/实时调用、结果展示（方案 §4.1/§4.3，rerun 安全）。
- **改动文件**：`web/app.py` 主流程（分析分支之外）新增 `_render_ai_fab()` 与 `_render_ai_result()`（代码见方案 §4.1/§4.3 原样）；顶部补充 `from src.ai.review import build_single_payload, call_ai, parse_review`。
- **实现要点**：
  - `_render_ai_fab()`：`st.button("🤖 AI 深度分析", key="ai_deep_analysis")` + `inject_ai_fab_js()`（每次 rerun）+ 三分支（AI 关 → warning 配置指引 / 未分析 → info 引导 / 正常 → `build_single_payload`→`call_ai`→`parse_review` 存 `ai_result`，异常 `warning` 降级）；
  - `_render_ai_result()`：`expander` 展示 `ai_result`，caption 标注 **标的/区间/周期**（防改参未重析误判）。
- **验证闸门**：`python -c "import web.app; from web.app import _render_ai_fab, _render_ai_result; print('app ok')"` 无报错。
- **完成标准**：函数存在、import 链通（含 `build_single_payload`/`call_ai`/`parse_review`）。

### Step 3.3 · 端到端验证（方案 §7 七条）
- **目标**：逐条核对 §7 验证计划。
- **验证闸门**（离线优先，用 `monkeypatch` 注入假 `call_ai` 返回样例 JSON，避免依赖网络/key）：
  ```bash
  streamlit run web/app.py
  ```
  逐项确认：
  1. `AI_ENABLED=False` → FAB 可见可点，点击给配置指引；「开始分析」照旧；
  2. 新会话直接点 FAB → 提示「请先开始分析」；
  3. 分析 `600588.SH` → 点 FAB → expander 展开，caption 标注标的/区间/周期；
  4. 分析 A 后改参不重析 → 点 FAB 仍基于 A，标注为 A（无拦截）；
  5. 选无分型极短区间 → 提示「未识别出分型，无需研判」，不调 AI；仅 1 分型 → 正常；
  6. `AI_BASE_URL` 填错 → 点击 `st.warning`，缠论图/蜡烛图仍在；
  7. `pytest src/ai/tests/test_payload.py` 已绿（Phase 1.2）。
  > 联网验证（可选）：在 `.env` 配有效 key 后重跑第 3 条，确认真实返回。
- **完成标准**：§7 七条全部满足；其他分析/绘图/监控功能不受影响；Phase 3 完成。

---

## Phase 4 · 文档（方案 §5 #5，可全程并行）

### Step 4.1 · `README.md` 新增小节
- **目标**：说明单标的 AI 深度分析入口。
- **改动文件**：`README.md` 新增「单标的 AI 深度分析」小节：入口（右下悬浮按钮）、引导逻辑（AI 关/未分析）、研判对象标注、降级说明。
- **验证闸门**：文档审阅通过，无事实性错误，且与方案 §4/§7 一致。
- **完成标准**：README 含该小节；Phase 4 完成。

---

## 附录 · §7 验证计划 → 步骤映射

| §7 条目 | 归属步骤 | 验证方式 |
|---|---|---|
| 1 AI 关闭态 | Step 3.3 | 手动 + 离线 mock |
| 2 未分析态 | Step 3.3 | 手动 |
| 3 正常态（caption 标注） | Step 3.2 / 3.3 | 手动 / 联网可选 |
| 4 旧上下文态 | Step 3.3 | 手动 |
| 5 边界（无分型/单分型） | Step 1.2 / 3.3 | 单测 + 手动 |
| 6 降级态 | Step 3.3 | 手动 |
| 7 单测 | Step 1.2 | `pytest` |

**交付判定**：Phase 1–4 全部绿灯，且 §7 七条通过 → 单标的方案实施完成。
