@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist "%~dp0runtime\python\python.exe" (
  echo 未找到内置 Python。请复制完整 TradingLabPortable 文件夹，不要只复制启动脚本。
  pause
  exit /b 2
)
if not exist "%~dp0runtime\python\python312.dll" (
  echo Python 运行库缺失。请恢复完整 runtime 目录。
  pause
  exit /b 2
)
"%~dp0runtime\python\python.exe" -I -B "%~dp0portable_control.py" start
set "TRADINGLAB_RESULT=%ERRORLEVEL%"
if not "%TRADINGLAB_RESULT%"=="0" pause
exit /b %TRADINGLAB_RESULT%
