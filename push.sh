#!/bin/bash
# push.sh - 每天零点自动推送Futures_Trading到GitHub

set -e

cd /home/admin/.openclaw/workspace/Futures_Trading

# Add all
git add .

# Check if there are changes
if git diff --cached --quiet; then
    echo "[$(date)] Futures_Trading: no changes, skip"
    exit 0
fi

# Commit with timestamp
git commit -m "Futures_Trading update $(date '+%Y-%m-%d %H:%M')"

# Push
git push origin main

echo "[$(date)] Futures_Trading pushed successfully"
