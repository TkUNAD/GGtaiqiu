@echo off
setlocal EnableExtensions
REM Use two-step cd: folder name contains (20260518) which breaks %~dp0backend

pushd "%~dp0"
cd /d backend
if errorlevel 1 (
  echo [ERROR] Cannot enter backend folder.
  popd
  pause
  exit /b 1
)

if not exist "venv\Scripts\python.exe" (
  echo Creating virtualenv...
  python -m venv venv
  if errorlevel 1 (
    echo [ERROR] Failed to create venv. Install Python 3 first.
    popd
    pause
    exit /b 1
  )
  call "venv\Scripts\activate.bat"
  pip install -r requirements.txt
) else (
  call "venv\Scripts\activate.bat"
)

echo.
echo Server starting...
echo Admin:  http://127.0.0.1:5000/admin
echo Screen: http://127.0.0.1:5000/screen
echo Health: http://127.0.0.1:5000/api/health
echo.

if not exist "..\wechat.secret.txt" if not exist "..\.env" (
  echo [WARN] WeChat Secret not configured. Run setup-wechat.bat
)

echo Checking .env security keys...
"venv\Scripts\python.exe" scripts\init_env.py
if errorlevel 1 (
  echo [ERROR] Failed to init .env
  popd
  pause
  exit /b 1
)
echo.

if not defined DEV_MODE set DEV_MODE=false

echo Running verify_fixes (optional)...
"venv\Scripts\python.exe" scripts\verify_fixes.py
if errorlevel 1 echo [WARN] verify_fixes failed - check data/backend

echo Stopping old server on port 5000 if any...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING"') do (
  taskkill /F /PID %%a >nul 2>&1
)

"venv\Scripts\python.exe" app.py
set ERR=%ERRORLEVEL%
popd
if not "%ERR%"=="0" pause
exit /b %ERR%
