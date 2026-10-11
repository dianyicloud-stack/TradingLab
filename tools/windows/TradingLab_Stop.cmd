@echo off
chcp 65001 >nul
setlocal
for %%I in ("%~dp0..\..") do set "TRADINGLAB_ROOT=%%~fI"
cd /d "%TRADINGLAB_ROOT%"
"%TRADINGLAB_ROOT%\.venv\Scripts\python.exe" -B "%TRADINGLAB_ROOT%\tools\runtime_control.py" stop --desktop
set "TRADINGLAB_RESULT=%ERRORLEVEL%"
if not "%TRADINGLAB_RESULT%"=="0" pause
exit /b %TRADINGLAB_RESULT%
