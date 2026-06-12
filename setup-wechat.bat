@echo off
setlocal EnableExtensions
pushd "%~dp0" || exit /b 1

if not exist ".env" (
  if exist ".env.example" copy /Y ".env.example" ".env" >nul
)

if not exist "wechat.secret.txt" (
  if exist "wechat.secret.example.txt" copy /Y "wechat.secret.example.txt" "wechat.secret.txt" >nul
  echo Created wechat.secret.txt
)

echo.
echo ========================================
echo  WeChat Mini Program Login Setup
echo ========================================
echo AppID (already set): wx4056ce1b5ca29798
echo.
echo STEP 1: Open mp.weixin.qq.com
echo         Development - Development Settings - AppSecret
echo         Copy AppSecret (reset if forgotten)
echo.
echo STEP 2: Edit wechat.secret.txt
echo         Paste AppSecret on ONE line (replace your_app_secret_here)
echo.
echo STEP 3: Restart run.bat
echo ========================================
echo.
notepad "wechat.secret.txt"
popd
pause
