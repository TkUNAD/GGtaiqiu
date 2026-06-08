# 安全配置说明

## 生产环境必配项

在项目根目录创建 `.env`（可参考 `.env.example`）：

| 变量 | 说明 |
|------|------|
| `SECRET_KEY` | Flask Session 签名密钥，勿使用默认值 |
| `JWT_SECRET` | 小程序 JWT 签名密钥 |
| `ADMIN_PASS` | 总后台管理员密码 |
| `DEV_MODE` | 必须为 `false` |
| `FLASK_DEBUG` | 必须为 `false` |
| `CORS_ORIGINS` | 允许的前端来源，逗号分隔 |

未配置时，`DEV_MODE=false` 启动将因默认密钥被拒绝。

首次运行 `run.bat` 若项目根目录无 `.env`，会自动执行 `scripts/init_env.py` 生成随机密钥并在控制台打印 `ADMIN_PASS`（请妥善保存）。

## 小程序认证

- 登录返回 `access_token` + `refresh_token`，不再使用 openid 作为 Token。
- 请求头：`Authorization: Bearer <access_token>`。
- 401 时客户端自动调用 `/api/auth/refresh`；失败则需重新微信授权登录。

## 管理后台

- 登录后 Session 含 `csrf_token`，所有写操作需 Header `X-CSRF-Token`。
- 登录失败连续 5 次后暂停 3 分钟（按 IP）；每次输错会提示已错次数与剩余可尝试次数。
- 球房会员过期后不可调分、处罚、删用户、开台加分等敏感操作。

### 修改 / 找回密码

| 场景 | 操作 |
|------|------|
| 登录页 | 「修改密码」：账号 + 当前密码 + 新密码 |
| 登录页 | 「忘记密码」：总后台 `admin` 需填写 `.env` 中 `JWT_SECRET` 作恢复密钥 |
| 登录后左下角 | 「修改密码」：当前密码 + 新密码（需已登录） |

总后台密码写入项目根 `.env` 的 `ADMIN_PASS`；修改后**无需重启**服务即可用新密码登录。

### 验证步骤（总后台 admin / admin123）

1. 重启 `run.bat`，浏览器打开 https://ggtaiqiu.com/admin（本地调试可用 http://127.0.0.1:5000/admin），`Ctrl+F5` 强刷。
2. 账号 `admin`、密码 `admin123`，回车或点登录 → 应进入仪表盘。
3. 登录页点「修改密码」：当前 `admin123`，新密码 `Admin1234!`，确认 → 提示成功；用新密码登录。
4. 左下角「修改密码」：改回 `admin123` → 再用 `admin123` 登录。
5. 忘记密码：先改成一个未知密码，再点「忘记密码」，恢复密钥填 `.env` 里 `JWT_SECRET` 整行值，新密码设 `admin123` → 用 `admin123` 登录。

命令行快速校验（在 `backend` 目录）：

```bat
venv\Scripts\python.exe -c "import config; print('ADMIN_PASS=', config.ADMIN_PASS)"
```

## 桌台二维码

- 新建桌台使用随机 `qr_token`，旧桌台若仍为 `table_T01` 格式，请在后台更新二维码并重新打印。

## HTTPS

- 小程序正式版必须使用 HTTPS 后端地址。
- 可选：`SESSION_COOKIE_SECURE=true`（HTTPS 管理后台）。

## 违规与封禁

- 严重违规累计 ≥3 次自动永久封禁。
- 球房后台可对玩家「记作弊」「永久封禁」。
