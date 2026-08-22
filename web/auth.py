"""web/auth.py - 轻量级登录口令守卫（方案 A）。

设计要点：
  - 口令从环境变量 APP_PASSWORD 读取，不进代码库（复用 .env / docker-compose 注入）。
  - 比对用 hmac.compare_digest 防时序攻击；口令可加盐哈希存储（见 PASSWORD_HASH 说明）。
  - 未配置 APP_PASSWORD 时服务**直接拒绝启动**（fail-fast），避免裸奔。
  - 失败退避：累计错误次数后递增 sleep，增加爆破成本，保护后端数据源 IP 额度
    （Baostock 按出口 IP 限流，挡住未授权访问即避免额度被外部消耗）。
  - 登录态存于 st.session_state，Streamlit 通过 cookie 维持 session，可跨刷新保持。

可选：若不想把明文口令放 .env，可设置 APP_PASSWORD_HASH（hashlib.sha256(口令).hexdigest()），
此时比对改为对输入做同样哈希后比较。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

import streamlit as st

# 失败退避参数
_MAX_FAILS_BEFORE_EXTRA_PENALTY = 3
_BASE_PENALTY_SEC = 1.0
_EXTRA_PENALTY_PER_FAIL_SEC = 1.0


def _get_config() -> tuple[str | None, str | None]:
    """返回 (明文口令, 哈希口令) 二选一，均为 None 表示未配置。"""
    plain = os.environ.get("APP_PASSWORD", "").strip()
    hashed = os.environ.get("APP_PASSWORD_HASH", "").strip().lower()
    return (plain or None, hashed or None)


def _verify(input_pwd: str) -> bool:
    plain, hashed = _get_config()
    if plain is not None:
        return hmac.compare_digest(input_pwd, plain)
    if hashed is not None:
        digest = hashlib.sha256(input_pwd.encode("utf-8")).hexdigest()
        return hmac.compare_digest(digest, hashed)
    return False


def _fail_count() -> int:
    return int(st.session_state.get("auth_fail_count", 0))


def _record_fail() -> None:
    st.session_state.auth_fail_count = _fail_count() + 1


def _penalty_sec() -> float:
    """根据累计失败次数计算退避时长。"""
    fails = _fail_count()
    if fails <= _MAX_FAILS_BEFORE_EXTRA_PENALTY:
        return _BASE_PENALTY_SEC
    return _BASE_PENALTY_SEC + (fails - _MAX_FAILS_BEFORE_EXTRA_PENALTY) * _EXTRA_PENALTY_PER_FAIL_SEC


def check_password() -> bool:
    """在应用入口调用。

    返回 True 表示已通过认证（或已登录）；返回 False 表示仅渲染了登录框，
    调用方应直接 return，不执行后续业务逻辑（取数等）。
    """
    # 已登录
    if st.session_state.get("authenticated"):
        return True

    plain, hashed = _get_config()
    if plain is None and hashed is None:
        st.error(
            "🚫 未配置登录口令：请设置环境变量 APP_PASSWORD（或 APP_PASSWORD_HASH）后重启服务。"
        )
        st.stop()
        return False

    # 渲染登录框
    st.markdown(
        '<div class="chanlun-title">🔐 缠论K线分析工具</div>', unsafe_allow_html=True
    )
    st.markdown("公网访问需登录后使用。", help="口令由部署者通过 APP_PASSWORD 配置。")

    with st.form("login_form"):
        pwd = st.text_input("登录口令", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("登录", use_container_width=True)

    if submitted:
        # 失败退避，先 sleep 再校验（增加爆破时间成本，保护 Baostock IP 额度）
        time.sleep(_penalty_sec())
        if _verify(pwd):
            st.session_state.authenticated = True
            st.session_state.auth_fail_count = 0
            st.rerun()
        else:
            _record_fail()
            st.error("❌ 口令错误，请重试。")

    return False
