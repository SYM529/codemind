@echo off
cd /d "%~dp0"
echo 正在构建并启动 CodeMind (server:3001 / client:8080)...
docker compose up -d --build
echo.
echo 启动完成，访问 http://localhost:8080
echo 健康检查: http://localhost:8080/api/health
pause
