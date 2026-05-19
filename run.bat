@echo off
cd /d "%~dp0backend"
if not exist venv (
  python -m venv venv
  call venv\Scripts\activate.bat
  pip install -r requirements.txt
) else (
  call venv\Scripts\activate.bat
)
echo 启动台球天梯系统...
echo 管理后台: http://127.0.0.1:5000/admin
echo 投屏大屏: http://127.0.0.1:5000/screen
python app.py
pause
