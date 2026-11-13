@echo off
setlocal
cd /d "%~dp0"
rem Creates .venv with Python 3.13 and installs requirements-fast.txt.
rem AroundWorldNG passes /launcher: no pause after success, it opens the window next.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
  if errorlevel 1 (
    echo The existing .venv cannot start its Python; it is recreated.
    goto create
  )
  goto install
)

:create
echo Creating Python virtual environment in .venv...
py -3.13 -m venv --clear .venv >nul 2>&1
if not errorlevel 1 goto install

py -3 -m venv --clear .venv >nul 2>&1
if not errorlevel 1 goto install

python -m venv --clear .venv >nul 2>&1
if not errorlevel 1 goto install

echo.
echo Python 3.10+ was not found on your system.
echo Please install Python 3.13 (or 3.11/3.12) for Windows from:
echo https://www.python.org/downloads/windows/
echo Make sure to tick "Add python.exe to PATH", "tcl/tk and IDLE" and "py launcher".
echo Then run AroundWorldNG.bat again.
pause
exit /b 1

:install
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-fast.txt
if errorlevel 1 (
  echo.
  echo Dependency installation failed. Check the messages above, your internet connection
  echo and antivirus, then run Setup.bat again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "%~dp0aroundworldng\launch_builder.py" --check --after-setup
if errorlevel 1 (
  pause
  exit /b 1
)
echo AroundWorldNG Map Builder is ready.
if /i not "%~1"=="/launcher" (
  echo Run AroundWorldNG.bat to open the window.
  pause
)
exit /b 0
