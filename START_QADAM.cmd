@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -WindowStyle Hidden -File "%~dp0Start-Qadam.ps1"
