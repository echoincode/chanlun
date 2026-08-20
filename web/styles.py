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
        </style>
        """,
        unsafe_allow_html=True,
    )
