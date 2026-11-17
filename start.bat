@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul || (echo 请先安装 Python 3.8 以上，安装时勾选 Add Python to PATH & pause & exit /b)
python server.py
pause
