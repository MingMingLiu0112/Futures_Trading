#!/bin/bash
# ============================================================
# VeighNa Docker Entry Point
# Supports multiple run modes: rpc, web, cli, shell
# ============================================================

set -e

# Default paths
export VNPY_DATA_PATH="${VNPY_DATA_PATH:-/app/data}"
export VNPY_LOG_PATH="${VNPY_LOG_PATH:-/app/logs}"
export VNPY_CONF_PATH="${VNPY_CONF_PATH:-/app/conf}"

mkdir -p "$VNPY_DATA_PATH" "$VNPY_LOG_PATH" "$VNPY_CONF_PATH"

# Proxy settings from environment
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:7890}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7890}"
export http_proxy="${http_proxy:-http://127.0.0.1:7890}"
export https_proxy="${https_proxy:-http://127.0.0.1:7890}"

# RPC service address configuration
export VNPY_RPC_REP_ADDRESS="${VNPY_RPC_REP_ADDRESS:-tcp://0.0.0.0:2014}"
export VNPY_RPC_PUB_ADDRESS="${VNPY_RPC_PUB_ADDRESS:-tcp://0.0.0.0:4102}"

# Database configuration
export VNPY_DATABASE="${VNPY_DATABASE:-sqlite}"  # sqlite, mongodb, mysql

# Web server port
export VNPY_WEB_PORT="${VNPY_WEB_PORT:-8765}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

wait_for_port() {
    local host="$1"
    local port="$2"
    local timeout="${3:-30}"
    log "Waiting for $host:$port to be available..."
    for i in $(seq 1 $timeout); do
        if nc -z "$host" "$port" 2>/dev/null; then
            log "$host:$port is available."
            return 0
        fi
        sleep 1
    done
    log "Timeout waiting for $host:$port"
    return 1
}

start_rpc() {
    log "Starting VeighNa RPC service..."
    log "  REP address: $VNPY_RPC_REP_ADDRESS"
    log "  PUB address: $VNPY_RPC_PUB_ADDRESS"

    cd /app
    python -c "
import sys
from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine
from vnpy.trader.database import get_database
from vnpy.rpc import RpcServer

# Initialize event engine
event_engine = EventEngine()
main_engine = MainEngine(event_engine)

# Initialize database
db = get_database()
print(f'Database initialized: $VNPY_DATABASE')

# Initialize RPC server
server = RpcServer()

# Register main engine methods
server.register(main_engine.subscribe)
server.register(main_engine.send_order)
server.register(main_engine.cancel_order)
server.register(main_engine.query_history)
server.register(main_engine.get_tick)
server.register(main_engine.get_order)
server.register(main_engine.get_trade)
server.register(main_engine.get_position)
server.register(main_engine.get_account)
server.register(main_engine.get_contract)
server.register(main_engine.get_all_ticks)
server.register(main_engine.get_all_orders)
server.register(main_engine.get_all_trades)
server.register(main_engine.get_all_positions)
server.register(main_engine.get_all_accounts)
server.register(main_engine.get_all_contracts)
server.register(main_engine.get_all_active_orders)

print('RPC server registered all methods')

# Start server
server.start('$VNPY_RPC_REP_ADDRESS', '$VNPY_RPC_PUB_ADDRESS')
print('RPC server started successfully')

import time
while True:
    time.sleep(1)
" &
    RPC_PID=$!
    log "RPC service started with PID $RPC_PID"

    # Also start REST API if available
    if python -c "import vnpy_restful" 2>/dev/null; then
        log "Starting REST API server on port $VNPY_WEB_PORT..."
        python -c "
from vnpy_restful import create_app
app = create_app()
app.run(host='0.0.0.0', port=$VNPY_WEB_PORT, debug=False, use_reloader=False)
" &
        REST_PID=$!
        log "REST API started with PID $REST_PID"
    fi

    # Wait for RPC process
    wait $RPC_PID
}

start_web() {
    log "Starting VeighNa Web UI mode..."
    log "Web port: $VNPY_WEB_PORT"

    if python -c "import vnpy_restful" 2>/dev/null; then
        cd /app
        exec python -c "
from vnpy_restful import create_app
app = create_app()
app.run(host='0.0.0.0', port=$VNPY_WEB_PORT, debug=False)
"
    else:
        log "ERROR: vnpy_restful not installed. Install with: pip install vnpy_restful"
        exit 1
    fi
}

start_cli() {
    log "Starting VeighNa in CLI mode..."
    cd /app
    exec python "${@:2}"
}

show_help() {
    echo "VeighNa Docker - Usage:"
    echo "  docker run vnpy [command] [args]"
    echo ""
    echo "Commands:"
    echo "  rpc          Start RPC service (default)"
    echo "  web          Start Web API server (FastAPI/Flask)"
    echo "  cli <script> Run a Python script in vnpy environment"
    echo "  shell        Start an interactive shell"
    echo "  help         Show this help message"
    echo ""
    echo "Environment Variables:"
    echo "  VNPY_DATA_PATH        Data directory (default: /app/data)"
    echo "  VNPY_LOG_PATH         Log directory (default: /app/logs)"
    echo "  VNPY_RPC_REP_ADDRESS  RPC REP address (default: tcp://0.0.0.0:2014)"
    echo "  VNPY_RPC_PUB_ADDRESS  RPC PUB address (default: tcp://0.0.0.0:4102)"
    echo "  VNPY_DATABASE         Database driver: sqlite|mongodb|mysql (default: sqlite)"
    echo "  VNPY_WEB_PORT         Web API port (default: 8765)"
    echo "  HTTP_PROXY/HTTPS_PROXY Proxy settings"
}

# Main entrypoint
case "${1:-rpc}" in
    rpc)
        start_rpc
        ;;
    web)
        start_web
        ;;
    cli)
        shift
        start_cli "$@"
        ;;
    shell)
        log "Starting interactive shell..."
        exec /bin/bash
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log "Unknown command: $1"
        show_help
        exit 1
        ;;
esac
