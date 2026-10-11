"""Deterministic launcher rendering, independent of old RC1 output paths."""
from pathlib import Path
def install(output):
 for name,action in [('Start','start'),('Stop','stop'),('Check','check')]:
  text='@echo off\r\nsetlocal\r\nchcp 65001 >nul\r\n"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0portable_bootstrap.ps1" -Action '+action+' %*\r\nset "result=%ERRORLEVEL%"\r\nif not defined TRADINGLAB_NONINTERACTIVE pause\r\nexit /b %result%\r\n'
  (Path(output)/(name+'.cmd')).write_bytes(text.encode('utf-8'))
if __name__=='__main__':raise SystemExit('Use Build-Portable.cmd; no implicit output mutation.')
