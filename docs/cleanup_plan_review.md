# 项目清理计划 · 审核意见

> 审核对象：`docs/cleanup_plan.md`
> 审核日期：2026-08-22
> 审核方法：grep 全项目 import 引用、文件存在性核查、tests 实际依赖核验

---

## 一、总体结论

清理计划的**方向正确**——扁平旧版文件确实应当迁出根目录，零引用的孤立文件应当清理。但在事实层面存在**多处重大偏差**：

1. **核心论断"全项目对根目录旧文件的 import 引用数为 0"严重失实**，多个旧文件仍有活引用。
2. **`tests/` 引用核对不全**，未考虑 docstring/注释中的提及不等于代码 import。
3. **部分文件被 README/文档/Phase 清单引用**，清理后会产生死链与文档不一致。
4. **`enhanced_viz.py` 与 `enhanced_visualizer.py` 的关系描述存在事实错误**。

| 原文档项 | 审核判定 | 结论摘要 |
|----------|----------|----------|
| 核验依据（引用数为 0） | ❌ 严重失实 | 至少 7 个旧文件仍有活引用 |
| A. 根目录扁平旧版文件 | ⚠️ 部分成立 | 部分文件确实零 import，但有的仍被旧入口引用 |
| B. `momentum_champion_bak.py` | ✅ 正确 | 孤立、引用方不存在，可删 |
| C. `app/main.py`、`app/utils.py` | ⚠️ 需复核 | main.py 自身引用 4 个旧文件 |
| D. 临时验证脚本 | ✅ 正确 | 确实零引用、走 `src.*` 路径 |
| E. `enhanced_viz.py` | ⚠️ 描述有误 | 与 `enhanced_visualizer.py` 内容**不同**，非"相同" |
| E. `gen_golden_samples.py` | ⚠️ 删除建议欠妥 | 仍被 README + Phase 文档引用 |

---

## 二、逐项审核详情

### ❌ 核心论断：引用数为 0 —— 严重失实

原文档第 14 行：

> `web/app.py` 仅 import `src.*` 与 `web.*`；全项目对根目录旧文件的 import 引用数为 **0**。

**审核事实**（grep 全项目代码文件 `.py`）：

| 旧文件 | 引用处 | 性质 |
|--------|--------|------|
| `baostock_data_fetcher.py` | `app/main.py:21`、`baostock_chanlun.py:10` | 活引用 |
| `mootdx_data_fetcher.py` | `app/main.py:20`、`mootdx_chanlun.py:11` | 活引用 |
| 根目录 `chanlun_processor.py` | `app/main.py:19`、`baostock_chanlun.py:9`、`mootdx_chanlun.py:10`、`scripts/gen_golden_samples.py:52` | 活引用（4 处）|
| `plotly_visualizer.py` | `app/main.py:22`、`baostock_chanlun.py:17,22`、`mootdx_chanlun.py:18,23` | 活引用（5 处）|
| `enhanced_visualizer.py` | `baostock_chanlun.py:14,25,219`、`mootdx_chanlun.py:15,26,307` | 活引用（6 处，含 try/except 兜底）|
| `tushare_client.py` | `scripts/gen_golden_samples.py:56` | 活引用 |
| `html.html` | 0 处 | ✅ 零引用 |

**结论**：除 `html.html` 外，A 组文件**没有一个是真正的零 import**。"引用数为 0" 的论断与事实严重不符。真正的零引用仅在以下三类：
- `html.html`
- `momentum_champion_bak.py`
- `scripts/_verify_*.py`

---

### ⚠️ A. 根目录扁平旧版文件 —— 部分成立

#### A1. `html.html` —— ✅ 成立
- 任何 .py / .md 文件均未引用，可安全删除。

#### A2. `baostock_data_fetcher.py` / `mootdx_data_fetcher.py` —— ⚠️ 删除风险
- 仍被 `app/main.py` 与同组旧入口活引用。
- 但 `app/main.py` 本身也在 C 组"待删"清单中——若**先**删 `app/main.py`，再删这两个 fetcher，引用链会同步断裂。
- **建议执行顺序**：先删 `app/`（C 组）→ 再删 fetcher（A 组）→ 最后删 `*_chanlun.py` 与 `chanlun_processor.py`。

#### A3. 根目录 `chanlun_processor.py` —— ⚠️ 删除风险
- 4 处活引用：`app/main.py`、`baostock_chanlun.py`、`mootdx_chanlun.py`、`scripts/gen_golden_samples.py`。
- 同样依赖 C 组与 `gen_golden_samples.py` 先处理。

#### A4. `plotly_visualizer.py` / `enhanced_visualizer.py` —— ⚠️ 删除风险
- `plotly_visualizer.py` 被 `app/main.py` + 两个旧 CLI 活引用。
- `enhanced_visualizer.py` 被两个旧 CLI 作为 try/except 兜底引用——若旧 CLI 已删，可一并清理。
- **关键事实更正**（详见 E 项）：原文档称 `enhanced_visualizer.py` "与 `src/visual/enhanced_viz.py` 内容相同"，**经核查不成立**：前者是根目录 Plotly 可视化实现，后者是 `src/visual/` 下 Matplotlib/mpld3 实现，二者内容**不同**。

#### A5. `baostock_chanlun.py` / `mootdx_chanlun.py` —— ⚠️ 删除风险
- 二者**自身**不被任何 `.py` 文件 import，但作为**脚本式运行**（`python baostock_chanlun.py`）是入口文件。
- 项目内作为模块的引用为 0，可视为"无活跃调用方"。

#### A6. `tushare_client.py` —— ⚠️ 删除风险
- 唯一活引用是 `scripts/gen_golden_samples.py:56`。
- 若该脚本删除，则可一并删除。

---

### ✅ B. `momentum_champion_bak.py` —— 成立

**审核事实**：
- 全项目 grep `momentum_champion` 仅返回 4 条结果，全部位于 `momentum_champion_bak.py` 自身（docstring 注释中提及）+ `docs/cleanup_plan.md:36` 1 条。
- 真正被引用的 `momentum_champion.py` **不存在**。
- 无任何代码文件 import 它。

**结论**：孤立无引用，可安全删除。✅

---

### ⚠️ C. 旧版 Web 入口 `app/main.py`、`app/utils.py` —— 需复核

**审核事实**：
- `app/main.py` 自身 import 4 个根目录旧文件（`chanlun_processor`、`mootdx_data_fetcher`、`baostock_data_fetcher`、`plotly_visualizer`）。
- `app/utils.py` 作为模块被项目内 import **0 次**（仅 main.py 可能在同一目录下引用，需进一步核查 main.py 内部是否引用）。
- 但 `docs/项目架构与算法分析.md:77` 明确写：`app/main.py → 过渡期保留，新入口为 web/app.py`；`docs/缠论项目工程优化-分步执行清单.md:39` 标注 Phase 5-3 状态为 ✅"app/main.py 顶部加过渡期旧入口注释… streamlit run app/main.py --server.port 8502 实测可正常启动"。

**结论**：
- `app/main.py` 是**已知有意保留的过渡期旧入口**，且当前 docstring 标记就是"过渡期"。
- 原清理计划直接列为待删，**未与 Phase 5/7 收尾的过渡策略对齐**。
- 建议：删除前确认 `streamlit run app/main.py` 已停止使用，并通知 docs 同步更新。

---

### ✅ D. 临时验证脚本 `_verify_runner_tmp.py`、`_verify_samples_tmp.py` —— 成立

**审核事实**：
- 两个脚本作为模块被项目内 import **0 次**。
- 命名带 `_tmp` 显然是临时验证遗留。
- `_verify_runner_tmp.py` 自身 import `src.cli.runner.fetch_data, analyze`，不影响现行架构。

**结论**：可安全删除。✅

---

### ⚠️ E. 待确认项 —— 描述偏差

#### E1. `src/visual/enhanced_viz.py` —— 描述正确，但归类不当

- 全项目 grep `enhanced_viz|enhanced_visualizer` 在 `src/` 与 `web/` 下均**返回 0 条结果**——证实确实是零引用的备选实现。
- 原文档定性"活代码路径零引用"成立。
- **但删除建议"或保留作备选"含糊**：建议明确二选一，避免悬而未决。

#### E2. `enhanced_viz.py` vs `enhanced_visualizer.py` 关系描述 —— ❌ 事实错误

原文档第 28 行：

> `enhanced_visualizer.py` — 旧版 matplotlib 可视化（与 `src/visual/enhanced_viz.py` 内容相同）

**核查事实**：
- 根目录 `enhanced_visualizer.py` 在两个旧 CLI 中作为 try/except fallback 引用（`baostock_chanlun.py:14,25,219`、`mootdx_chanlun.py:15,26,307`）。
- 实际内容是 Plotly 可视化相关。
- `src/visual/enhanced_viz.py` 是 Matplotlib/mpld3 实现，**两者不是相同内容**，命名虽然相似但功能与依赖不同。
- 原文档"内容相同"的断言**与事实不符**，需修正。

#### E3. `scripts/gen_golden_samples.py` —— 删除建议欠妥

- 自身确实 import 了根目录旧 `chanlun_processor`（52 行）与 `tushare_client`（56 行），运行会失败——这一事实正确。
- 但该脚本**仍被多处引用**：
  - `README.md:57` 标注为"黄金样本生成脚本（调试用）"
  - `docs/缠论项目工程优化-分步执行清单.md:71` 标注为脚本链接
  - `docs/缠论项目工程优化-分步执行清单.md:132,153,546` 多次提及
  - `src/data/tushare_fetcher.py:6,245,292` 注释中明确"吸收自 `gen_golden_samples.py` 的列映射逻辑"
  - `src/config/settings.py:21` 注释中提及
  - `tests/verify_tushare_fetcher.py:10,56` 注释中提及

**结论**：
- 直接删除会产生 6+ 处文档/注释死链。
- 且脚本的**算法参考价值**已被 `src/data/tushare_fetcher.py` 吸收，但**作为历史样本/回归基准**仍有保留意义。
- **建议**：先修复 import 让其可运行，或在删除前先把所有引用方同步更新/移除引用——不要单独删除此文件。

---

## 三、原文档遗漏的额外问题（补充）

1. **执行顺序未指定**：C 组（`app/main.py`）和 A 组（fetcher/`chanlun_processor.py`）存在引用耦合，必须按 C → A 顺序删除，否则会留下 import 失效的中间态。
2. **`docs/` 死链清理不完整**：原文档第 70 行提到"`docs/enhanced_visualizer.md`、`docs/项目架构与算法分析.md` 等"，但实际有 **14 个文档文件**涉及旧路径（grep 结果），清理清单需要补全。
3. **`app/main.py` 的过渡期策略冲突**：原清理计划未与 `docs/缠论项目工程优化-分步执行清单.md` 的 Phase 5/7 收尾策略对齐，建议先确认 Phase 7 是否已完成再删。
4. **`docs/fractal_bugs_analysis.md` 与 `docs/fractal_bugs_analysis_review.md` 未在保留清单中显式提及**：这两个文档本身不在删除范围，但清理计划应把"全部保留的 docs/"明确列出，避免误删。

---

## 四、修正版执行步骤建议

按依赖顺序安全清理：

1. **先处理依赖上游**：
   - 修复或删除 `scripts/gen_golden_samples.py`（同步更新 README + Phase 清单 + `src/data/tushare_fetcher.py` 注释 + `tests/verify_tushare_fetcher.py` 注释）。
   - 决定 `src/visual/enhanced_viz.py` 去留（二选一）。

2. **删除 C 组（先删入口，断引用链）**：
   - `app/main.py`、`app/utils.py`（若确认过渡期已结束）。

3. **删除 A 组（根目录扁平旧文件）**：
   - `baostock_chanlun.py`、`mootdx_chanlun.py`
   - `baostock_data_fetcher.py`、`mootdx_data_fetcher.py`
   - 根目录 `chanlun_processor.py`
   - `plotly_visualizer.py`、`enhanced_visualizer.py`
   - `tushare_client.py`
   - `html.html`

4. **删除 B、D 组**（独立无引用）：
   - `momentum_champion_bak.py`
   - `scripts/_verify_runner_tmp.py`、`scripts/_verify_samples_tmp.py`

5. **同步清理 docs 死链**（14 个文档需逐一核对）。

6. **运行 `tests/` 验证 + 提交**。

---

## 五、审核结论汇总

| 类别 | 原计划判定 | 审核修正 |
|------|-----------|----------|
| 总体可行性 | 方向正确 | ✅ |
| 引用数 0 的核心论断 | —— | ❌ 失实，需重写核验依据 |
| A 组删除 | 全部安全 | ⚠️ 需先处理 C 组与 `gen_golden_samples.py` |
| B 组删除 | 安全 | ✅ |
| C 组删除 | 视为待删 | ⚠️ 与过渡期策略冲突，需确认 |
| D 组删除 | 安全 | ✅ |
| E1 `enhanced_viz.py` | 备选/保留含糊 | ⚠️ 建议二选一明确 |
| E2 `enhanced_viz` 与 `enhanced_visualizer` 关系 | "内容相同" | ❌ 事实错误，内容不同 |
| E3 `gen_golden_samples.py` | 可删 | ⚠️ 删除前需同步 6+ 处引用方 |

**一句话总结**：清理计划的**意图和大部分清单项是正确的**，但**核心论断（引用数为 0）与部分事实描述（enhanced_viz 内容相同、gen_golden_samples 可删）有重大错误**。建议按"先断引用链（C + gen_golden_samples）→ 再删 A/B/D → 最后同步 docs"的顺序执行，避免中间态 import 失效与文档死链。