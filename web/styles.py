"""web/styles.py - Streamlit 页面样式模块（Phase 5 · Step 5-1）

存放内联 CSS，通过 st.markdown(unsafe_allow_html=True) 注入，美化标题、按钮、
提示框、免责提示栏。**纯样式，不含任何业务计算逻辑**。

常量引用 src.config.settings（如 CHART_HEIGHT），仅用于样式取值。
"""
from __future__ import annotations

import streamlit as st

from src.config.settings import CHART_HEIGHT


def inject_styles() -> None:
    """注入全局 CSS 样式（在 st.set_page_config 之后、页面内容之前调用一次）。"""
    st.markdown(
        f"""
        <style>
        /* 主标题 */
        .chanlun-title {{
            text-align: center;
            padding: 0.6rem 0 0.2rem 0;
            color: #1f3a5f;
            font-size: 2rem;
            font-weight: 700;
        }}
        /* 副标题 */
        .chanlun-subtitle {{
            text-align: center;
            color: #6b7280;
            margin-bottom: 0.8rem;
            font-size: 0.95rem;
        }}
        /* 免责提示栏 */
        .chanlun-disclaimer {{
            background: #fff8e1;
            border: 1px solid #f0d488;
            border-left: 5px solid #f0a500;
            border-radius: 6px;
            padding: 0.55rem 1rem;
            margin: 0.8rem 0 1.2rem 0;
            color: #5c4a00;
            font-size: 0.85rem;
            line-height: 1.5;
        }}
        /* 提示框圆角增强 */
        div[data-testid="stAlert"] {{
            border-radius: 8px;
        }}
        /* 按钮整行宽度 */
        .stButton > button {{
            width: 100%;
        }}
        /* 图表容器高度（来自 settings.CHART_HEIGHT，供 use_container_width 图表外框使用） */
        .chanlun-chart-box {{
            height: {CHART_HEIGHT}px;
        }}
        /* AI 深度分析悬浮按钮（FAB）：右下圆角浮动，避让 Streamlit 状态控件 */
        .ai-fab > button {{
            position: fixed !important;
            right: 28px; bottom: 64px; z-index: 999;
            width: auto !important; min-width: 132px;
            padding: 0.6rem 1.1rem;
            border-radius: 999px;
            background: linear-gradient(135deg, #2563eb, #1e40af);
            color: #fff; font-weight: 600;
            box-shadow: 0 8px 24px rgba(30,64,175,.35);
        }}
        .ai-fab > button:hover {{ filter: brightness(1.08); }}
        /* AI 弹窗内容卡片 */
        .ai-card {{
            background: #fff; border: 1px solid #e5e7eb; border-radius: 10px;
            padding: 0.7rem 0.9rem; margin: 0.5rem 0;
            box-shadow: 0 1px 3px rgba(0,0,0,.05);
        }}
        .ai-card-title {{ font-weight: 700; color: #1f3a5f; margin-bottom: 0.25rem; }}
        .ai-card-body {{ color: #374151; font-size: 0.9rem; line-height: 1.6; }}
        .ai-card-warn {{ background: #fff7ed; border-color: #fdba74; }}
        .ai-card-info {{ background: #eff6ff; border-color: #93c5fd; }}
        /* 弹窗内按钮间距 */
        .stDialog > div > div {{ max-width: 920px; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_ai_fab_js() -> None:
    """将「🤖 AI 深度分析」按钮浮到右下角（按 label 定位；JS 不可用则回退普通按钮）。

    Streamlit 原生 st.button 无法指定 class，故用 JS 按按钮唯一 label 找到其容器并加浮动类。
    ★ 必须在每次 rerun 后重新注入（Streamlit 重跑会重建 DOM），由 _render_ai_fab() 调用。
    """
    JS = """
    <script>
    (function () {
      var label = "AI 深度分析";
      var btns = window.parent.document.querySelectorAll("button");
      for (var i = 0; i < btns.length; i++) {
        if (btns[i].innerText && btns[i].innerText.indexOf(label) >= 0) {
          btns[i].parentElement.classList.add("ai-fab");
        }
      }
    })();
    </script>
    """
    st.components.v1.html(JS, height=0, width=0)
