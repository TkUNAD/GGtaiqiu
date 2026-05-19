@echo off
echo 正在为台球天梯后端开放 5000 端口（需管理员权限）...
netsh advfirewall firewall delete rule name="BilliardsLadder5000" >nul 2>&1
netsh advfirewall firewall add rule name="BilliardsLadder5000" dir=in action=allow protocol=TCP localport=5000
if %errorlevel%==0 (
  echo 防火墙规则已添加，真机可通过局域网访问 http://你的IP:5000
) else (
  echo 添加失败，请右键「以管理员身份运行」本脚本
)
pause
