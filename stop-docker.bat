@echo off
cd /d "%~dp0"
docker compose down
echo CodeMind 已停止。
pause
