@echo off
echo TradingLab DEV / TEST - isolated local services
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\dev\bootstrap.ps1" -Action start %*
exit /b %errorlevel%
