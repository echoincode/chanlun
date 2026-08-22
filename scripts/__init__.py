"""scripts 包：可独立运行的脚本集合（监控任务 / Tushare 测试等）。

允许 web.app 通过 `from scripts.monitor_job import run_monitor` 复用监控逻辑。
"""