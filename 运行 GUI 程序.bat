@echo off
chcp 65001 > nul
title Bilibili 批量下载助手

echo 正在检查 Python 环境...
python --version > nul 2>&1
if errorlevel 1 (
    echo Python 未安装或未添加到环境变量！
    echo 请安装 Python 3.8 或更高版本，并确保已添加到环境变量。
    pause
    exit /b 1
)

echo 正在检查依赖...
pip show customtkinter > nul 2>&1
if errorlevel 1 (
    echo 正在安装 customtkinter...
    pip install customtkinter
)

pip show yt-dlp > nul 2>&1
if errorlevel 1 (
    echo 正在安装 yt-dlp...
    pip install yt-dlp
)

pip show requests > nul 2>&1
if errorlevel 1 (
    echo 正在安装 requests...
    pip install requests
)

pip show rich > nul 2>&1
if errorlevel 1 (
    echo 正在安装 rich...
    pip install rich
)

echo 正在启动程序...
python gui_downloader.py
if errorlevel 1 (
    echo 程序启动失败！
    pause
    exit /b 1
)

pause 