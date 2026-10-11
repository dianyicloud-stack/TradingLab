@echo off
setlocal
chcp 65001 >nul
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0portable-work\build.ps1" %*
set "result=%ERRORLEVEL%"
if not defined TRADINGLAB_NONINTERACTIVE pause
exit /b %result%
