@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0scripts\install_mod.ps1" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_mod.ps1"
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $s = (New-Object Net.WebClient).DownloadString('https://raw.githubusercontent.com/wilszzz/aroundworldng/main/scripts/install_mod.ps1'); Invoke-Expression $s"
)
exit /b %errorlevel%
