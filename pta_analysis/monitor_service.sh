#!/bin/bash
# PTA分析平台监控脚本

LOG_FILE="/tmp/pta_web_monitor.log"
FLASK_PORT=8422
NGINX_PORT=80

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

check_flask() {
    if ! curl -s http://127.0.0.1:$FLASK_PORT/health > /dev/null 2>&1; then
        log "Flask应用异常，尝试重启..."
        pkill -f "python3 web_app.py"
        sleep 2
        cd /home/admin/.openclaw/workspace/codeman/pta_analysis
        nohup python3 web_app.py > /tmp/flask.log 2>&1 &
        sleep 5
        if curl -s http://127.0.0.1:$FLASK_PORT/health > /dev/null 2>&1; then
            log "Flask应用重启成功"
        else
            log "Flask应用重启失败"
        fi
    else
        log "Flask应用运行正常"
    fi
}

check_nginx() {
    if ! curl -s http://127.0.0.1:$NGINX_PORT/ > /dev/null 2>&1; then
        log "Nginx异常，尝试重启..."
        sudo systemctl restart nginx
        sleep 3
        if curl -s http://127.0.0.1:$NGINX_PORT/ > /dev/null 2>&1; then
            log "Nginx重启成功"
        else
            log "Nginx重启失败"
        fi
    else
        log "Nginx运行正常"
    fi
}

check_external() {
    if curl -s http://47.100.97.88/ > /dev/null 2>&1; then
        log "外部访问正常"
    else
        log "外部访问异常"
    fi
}

# 主监控循环
log "开始PTA分析平台监控..."
while true; do
    log "=== 监控检查开始 ==="
    check_flask
    check_nginx
    check_external
    log "=== 监控检查结束 ===\n"
    sleep 300  # 每5分钟检查一次
done