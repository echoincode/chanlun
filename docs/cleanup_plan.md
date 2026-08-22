# 项目清理计划（删除无用代码与文件）

> 生成日期：2026-08-22
> 修订日期：2026-08-22（合并审核意见）
> 目的：移除改造前的扁平旧版文件、备份文件、临时脚本与死代码，保留以 `src/` 为核心、`web/app.py` 为入口的现行架构。

## 一、现行架构（保留，勿动）

- **入口**：`web/app.py`（Streamlit）、`src/cli/runner.py`（CLI）
- **核心**：`src/core/chanlun_processor.py`、`src/data/*`、`src/visual/plotly_viz.py`、`src/config/*`、`src/utils/*`
- **前端**：`web/auth.py`、`web/styles.py`
- **脚本**：`scripts/run_tushare.py`
- **测试**：`tests/*.py`

**核验依据（重要）**：经 grep 实测，活跃架构目录（`web/`、`src/`、`tests/`、`scripts/` 除待删脚本外）对根目录旧文件的 import 引用数均为 **0**：

| 活跃目录 | 引用根目录旧文件 |
|---------|------------------|
| `web/app.py` | 仅 `src.*` + `web.*`（0 处旧文件） |
| `src/` | 0 处 |
| `tests/` | 0 处 |
| `scripts/`（除 `gen_golden_samples.py`） | 0 处 |

> 说明：旧文件之间（如 `app/main.py`、`baostock_chanlun.py` 等）存在相互 import，但这些引用方本身都在本清理清单内（C 组 / A 组 / E 组），删除时一并消失，引用链同步断裂，不影响活跃架构。故"引用数为 0"特指**活跃架构**，而非待删文件内部。

## 二、待删除清单

### A. 根目录扁平旧版文件（已被 `src/` 取代）

| 文件 | 说明 | 对应现版 |
|------|------|----------|
| `baostock_chanlun.py` | 旧版 BaoStock CLI 入口，v4 已弃用 | `src/cli/runner.py` + `src/data/baostock_fetcher.py` |
| `baostock_data_fetcher.py` | 旧版数据获取器 | `src/data/baostock_fetcher.py` |
| `mootdx_chanlun.py` | 旧版 Mootdx 入口，v4 已弃用 | `src/cli/runner.py` |
| `mootdx_data_fetcher.py` | 旧版数据获取器 | `src/data/*`（pytdx 路径） |
| `chanlun_processor.py` | 旧版核心算法（扁平副本） | `src/core/chanlun_processor.py` |
| `plotly_visualizer.py` | 旧版 Plotly 可视化 | `src/visual/plotly_viz.py` |
| `enhanced_visualizer.py` | 根目录 Plotly 实现（**与 `src/visual/enhanced_viz.py` 功能/依赖不同**：本文件为 Plotly 版，enhanced_viz.py 为 Matplotlib/mpld3 版，二者非同一文件） | `src/visual/enhanced_viz.py`（若保留） |
| `tushare_client.py` | 旧版 Tushare 客户端 | `src/data/tushare_fetcher.py` |
| `html.html` | 遗留的"Baostock 知识库"静态网页，与项目无关，含百度统计脚本 | 无 |

### B. 备份/孤立文件

| 文件 | 说明 |
|------|------|
| `momentum_champion_bak.py` | 文件名带 `_bak` 的备份脚本，自身引用的 `momentum_champion.py` 不存在，孤立无引用 |

### C. 旧版 Web 入口目录（⚠️ 过渡期保留项，删除前需确认）

| 路径 | 说明 |
|------|------|
| `app/main.py` | 改造前 Streamlit 入口（注释标记"过渡期旧入口"），import 全部为根目录旧文件。README 标注"Phase 7 待删除"，Phase 清单 5-3 明确为过渡期保留 |
| `app/utils.py` | 同上，随 `app/main.py` 一并弃用 |

> 注：README.md 与 docs 多处将其列为"过渡期保留，新入口为 web/app.py"。删除前请确认是否已进入 Phase 7 收尾；本次操作先移到 `delete/` 暂存（非直接 git rm），可随时回退。

### D. 临时验证脚本

| 文件 | 说明 |
|------|------|
| `scripts/_verify_runner_tmp.py` | 命名带 `_tmp` 的临时验证脚本（已引用 `src.*`，验证完成后遗留） |
| `scripts/_verify_samples_tmp.py` | 同上 |

### E. 死代码（当前活跃路径无引用）

| 文件 | 说明 | 处置 |
|------|------|------|
| `src/visual/enhanced_viz.py` | Matplotlib/mpld3 备选可视化，活跃代码零引用（仅文档提及）；与根目录 `enhanced_visualizer.py` 是**不同文件** | 本次移到 `delete/` 暂存（如需 Plotly/mpld3 备选可留，暂按清理处理） |
| `scripts/gen_golden_samples.py` | 样本生成工具，但 import 根目录旧 `chanlun_processor`/`tushare_client`（运行会失败）；被 README + Phase 文档引用 | **先修复 import 指向 `src.*` 再保留**，或移到 `delete/`。本次按"移到 delete/ 暂存"处理，保留修复可能性 |

## 三、不建议删除

- `src/**`、`web/**`、`scripts/run_tushare.py`、`tests/**`、`docs/**`、`requirements.txt`、`Dockerfile`、`docker-compose.yml`、`.env.example`、README.md、`chanlun_ch.md` 规范文档
- `__pycache__` / `*.pyc`：建议将 `__pycache__/` 与 `*.pyc` 加入 `.gitignore` 防止提交

## 四、执行步骤（已确认）

> 按"先断引用链（C）→ 再删 A/B/D → 最后 E"顺序，避免中间态 import 失效。所有待删项先移动到 `delete/` 暂存目录（非直接删除），便于回退与复核。

1. 创建 `delete/` 目录
2. 移动 C 组：`app/main.py`、`app/utils.py` → `delete/app/`
3. 移动 A 组：9 个根目录旧文件 → `delete/root/`
4. 移动 B 组：`momentum_champion_bak.py` → `delete/root/`
5. 移动 D 组：`scripts/_verify_runner_tmp.py`、`scripts/_verify_samples_tmp.py` → `delete/scripts/`
6. 移动 E 组：`src/visual/enhanced_viz.py` → `delete/src_visual/`；`scripts/gen_golden_samples.py` → `delete/scripts/`
7. 运行 `tests/` 验证活跃架构无回归
8. 同步清理 `docs/*.md` 中对已移文件的引用（如 `docs/enhanced_visualizer.md`、`docs/项目架构与算法分析.md`、README 等提及旧路径/过渡期处）
9. 提交推送（若 `delete/` 也需纳入版本管理，可一并提交；否则加 `.gitignore` 忽略 `delete/`）

## 五、影响评估

- 活跃架构（`web/app.py` → `src.*`）完全不受影响，删除/移动后对活跃代码零 import 依赖。
- `tests/` 引用 `src.*`，不受清理影响。
- `app/main.py` 为过渡期入口，本次仅移到 `delete/` 暂存，`streamlit run web/app.py` 仍正常。
- `gen_golden_samples.py` 移到 `delete/` 前若需保留，应改 import：`chanlun_processor` → `src.core.chanlun_processor`、`tushare_client` → `src.data.tushare_fetcher`，并同步 README/Phase 文档引用。

---
*本文件为删除说明。实际删除操作：先移动到 `delete/` 暂存，确认无误后再决定是否彻底清除。*
