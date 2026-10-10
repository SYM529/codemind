@echo off
echo ========================================
echo CodeMind - AI 代码理解与文档生成助手 启动脚本
echo ========================================

echo 检查Node.js安装...
node --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未检测到Node.js,请先安装Node.js
    pause
    exit /b 1
)

echo Node.js已安装,版本: 
node --version

echo.
echo 安装项目依赖...
call npm run install-all

if errorlevel 1 (
    echo 错误: 依赖安装失败
    pause
    exit /b 1
)

echo.
echo 启动开发服务器...
echo 前端服务将运行在: http://localhost:8080
echo 后端服务将运行在: http://localhost:3001
echo.
echo 按 Ctrl+C 停止服务
echo.

call npm run dev

pause