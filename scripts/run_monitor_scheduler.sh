#!/usr/bin/env bash
# 每日收盘分型监控调度器（容器内常驻）。
#
# 逻辑：
#   - 每分钟唤醒一次，读取 NOTIFY_TIME（HH:MM，本地时区）与 MONITOR_CODES；
#   - 非交易日（周六/周日）直接跳过；
#   - 到了目标时刻（当天该分钟内首次命中）触发一次 monitor_job.py；
#   - 同一天只跑一次（基于 state/last_monitor_date 去重），避免重启/时区抖动重复推送。
#
# 设计取舍：python:3.11-slim 不保证装了 cron，故用纯 bash 循环 + sleep 60，
# 轻量且无外部依赖；日志打到 stdout，交给 docker logs 收集。
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

NOTIFY_TIME="${NOTIFY_TIME:-16:30}"
TARGET_HH="${NOTIFY_TIME%%:*}"
TARGET_MM="${NOTIFY_TIME##*:}"

echo "[scheduler] 启动 | 目标时刻=${NOTIFY_TIME} | MONITOR_CODES=${MONITOR_CODES:-<空>}"

STATE_DIR="${PROJECT_ROOT}/state"
LAST_FILE="${STATE_DIR}/last_monitor_date.txt"

mkdir -p "$STATE_DIR"

while true; do
    now=$(date '+%H:%M')
    today=$(date '+%Y-%m-%d')
    dow=$(date '+%u')   # 1=周一 ... 7=周日

    # 跳过周末（1-5 为交易日；含法定节假日未处理，与 monitor_job 一致）
    if [ "$dow" -ge 6 ]; then
        sleep 60
        continue
    fi

    if [ "$now" = "${TARGET_HH}:${TARGET_MM}" ]; then
        # 当天已跑过则跳过（防重复）
        if [ -f "$LAST_FILE" ] && [ "$(cat "$LAST_FILE")" = "$today" ]; then
            sleep 60
            continue
        fi

        echo "[scheduler] ${today} ${now} 触发监控..."
        if python -m scripts.monitor_job; then
            echo "$today" > "$LAST_FILE"
            echo "[scheduler] ${today} 监控完成"
        else
            echo "[scheduler] ${today} 监控执行失败（非零退出），将于下一分钟重试" >&2
        fi
    fi

    sleep 60
done
