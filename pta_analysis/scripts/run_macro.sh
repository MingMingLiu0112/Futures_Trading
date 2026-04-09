#!/bin/bash
# PTA宏观分析定时脚本 - 三维框架完整版
# 每天 17:30 定时推送（下午盘结束后数据最新）
# 自动同步最新脚本到容器后执行
SCRIPT_HOST="/home/admin/.openclaw/workspace/codeman/pta_analysis/scripts/full_report.py"
podman cp "$SCRIPT_HOST" vnpy-beta:/tmp/full_report.py
podman exec vnpy-beta python3 /tmp/full_report.py >> /tmp/macro.log 2>&1
