"""src/ai - AI 研判模块（OpenAI 兼容）。

提供：
  - call_ai(payload)：调用大模型，返回 JSON 文本；
  - parse_review(text)：解析研判结果，返回标准化 dict；
  - build_single_payload(...)：组装单标的深度分析 payload（悬浮按钮用）。

凭据（API Key / Base URL / Model）全部来自 src.config.settings，仅环境变量读取。
本模块被「单标的悬浮按钮」与「收盘批量监控」共用，不含任何业务触发逻辑。
"""
