@echo off
cd /d "%~dp0"
echo 正在构建并启动 CodeMind (mysql / server:3002 / client:8081)...
docker compose up -d --build
echo.
echo 启动完成，访问 http://localhost:8081
echo 健康检查: http://localhost:3002/api/health
pause
