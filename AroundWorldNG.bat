@echo off
setlocal
cd /d "%~dp0"
rem AroundWorldNG Map Builder Launcher
title AroundWorldNG — Студия и генератор карт для BeamNG.drive

if exist "%~dp0aroundworldng\launch_builder.py" (
  set "LAUNCHER=%~dp0aroundworldng\launch_builder.py"
) else (
  echo Файлы AroundWorldNG не найдены.
  echo Убедитесь, что папка aroundworldng находится рядом с батником.
  pause
  exit /b 1
)

call :find
if not defined PY (
  call "%~dp0Setup.bat" /launcher
  if errorlevel 1 exit /b 1
  call :find
)
if not defined PY (
  echo Setup.bat не смог создать .venv\Scripts\python.exe.
  pause
  exit /b 1
)

"%PY%" "%LAUNCHER%" %*
set "RC=%errorlevel%"
if "%RC%"=="0" exit /b 0
if "%RC%"=="2" goto done

:setup
echo Запуск Setup.bat для настройки окружения и установки пакетов...
call "%~dp0Setup.bat" /launcher
if errorlevel 1 exit /b 1
set "PY=%~dp0.venv\Scripts\python.exe"
"%PY%" "%LAUNCHER%" --after-setup %*

:done
if "%RC%"=="0" exit /b 0
if not "%RC%"=="2" (
  echo.
  echo Python at "%PY%" failed with code %RC%.
  echo Delete the .venv folder here and run AroundWorldNG.bat again.
)
pause
exit /b %RC%

:find
set "PY="
if exist "%~dp0python\python.exe" (
  set "PY=%~dp0python\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
  set "PY=%~dp0.venv\Scripts\python.exe"
)
exit /b 0
