# 台球天梯系统（商用完整版）

Python Flask + SocketIO 后端 | 微信原生小程序 | 电视投屏大屏 | 管理后台

## 功能清单

- **6段5星段位**：新锐学徒(1000+) ~ 殿堂球王(2000+)，初始1000分
- **排位积分规则**：高低分胜负差异化加减分
- **日常加分**：开台/有效局/炸清/接清/单杆50+/破百
- **赛季**：每月1赛季；周榜每周清零
- **7天未对战**每天-5分；**30天未登录**隐藏排名
- **排位挑战**：仅可挑战高1~5名；日限2场/周限9场
- **桌台扫码对战**：抢5/抢7；胜负互认；60秒冷却；未满局减半
- **防刷**：开台才能排位、一桌一局、IP/手机限制、短局无效、积分预警、封禁公示
- **积分商城**：兑换 + 后台审核发放
- **管理后台** `/admin`：审核、调分、开台、商品、导出Excel、封禁
- **投屏大屏** `/screen`：TOP20 + 实时桌台 + SocketIO 刷新

## 快速启动

### 1. 后端

```bash
cd backend
python -m venv venv
venv\Scripts\activate    # Windows
pip install -r requirements.txt
python app.py
```

或双击项目根目录 `run.bat`

- 线上 API: https://ggtaiqiu.com
- 管理后台: https://ggtaiqiu.com/admin
- 投屏大屏: https://ggtaiqiu.com/screen
- 本地调试: http://127.0.0.1:5000 （`run.bat` 启动）

环境变量（可选，也可用项目根目录 `.env` / `wechat.secret.txt`）：

| 变量 | 说明 |
|------|------|
| ADMIN_USER / ADMIN_PASS | 管理员账号密码 |
| PUBLIC_URL | 线上域名，默认 `https://ggtaiqiu.com` |
| CORS_ORIGINS | 允许跨域来源，默认含 `ggtaiqiu.com` 与本地 |
| WECHAT_APPID / WECHAT_SECRET | 微信小程序正式登录 |
| DEV_MODE=false | 关闭开发模式，启用真实微信登录 |
| PORT | 端口，默认5000 |

配置微信登录：双击 **`setup-wechat.bat`**，详见 [docs/wechat-login.md](docs/wechat-login.md)。

### 2. 微信小程序

首次克隆后生成 TabBar 图标（仅需一次）：

```bash
python scripts/generate_assets.py
```

1. 用微信开发者工具打开**项目根目录**（已配置 `miniprogramRoot`）或只打开 `miniprogram` 目录
2. 修改 `project.config.json` 中的 `appid` 为你的小程序 AppID
3. 真机/体验版/正式版默认请求 `https://ggtaiqiu.com`，须在微信公众平台配置 **request 合法域名** `ggtaiqiu.com`
4. 本地真机联调：开发者工具勾选「不校验合法域名」，并在控制台执行 `setManualApiBase('http://192.168.x.x:5000')`（`ipconfig` 查看局域网 IP）
5. 若本地联调连不上，右键以管理员运行项目根目录 `open_firewall.bat` 开放 5000 端口

### 3. 桌台二维码

二维码内容示例（可生成打印贴桌）：

```
https://ggtaiqiu.com/pages/table/table?table_id=T01&qr_token=table_T01
```

或使用小程序码，scene 携带 `table_id` 与 `qr_token`。

桌台数据在 `backend/data/tables.json`，默认 T01~T04。

## 文档

| 文档 | 说明 |
|------|------|
| [docs/deploy-wxcloud.md](docs/deploy-wxcloud.md) | **微信云托管**部署、端口与环境变量 |
| [docs/wechat-login.md](docs/wechat-login.md) | 微信授权登录流程、接口、配置与排错 |
| [docs/scoring-rules.md](docs/scoring-rules.md) | 排位/休闲/炸清接清等加分规则 |

## 目录结构

```
├── docs/                # 说明文档
├── backend/
│   ├── app.py           # Flask + SocketIO 主程序
│   ├── config.py        # 配置
│   ├── db.py            # JSON 存储
│   ├── rating.py        # 段位积分规则
│   ├── anti_cheat.py    # 防刷
│   ├── services.py      # 业务逻辑
│   ├── data/            # JSON 数据库（自动创建）
│   └── templates/
│       ├── admin.html   # 管理后台
│       └── screen.html  # 投屏大屏
├── miniprogram/         # 微信原生小程序
│   └── pages/
│       ├── index/ rank/ table/ profile/ shop/
├── setup-wechat.bat     # 配置微信 AppSecret
└── run.bat
```

## 管理后台操作

1. **开台**：桌台管理 → 开台（可关联用户计开台小时+8分/小时）
2. **审核兑换**：兑换审核 → 发放/拒绝
3. **调分/封禁**：玩家管理
4. **导出对局**：对局管理 → 导出 Excel

## 注意事项

- 生产环境请使用 gunicorn + eventlet 部署 SocketIO
- 数据备份请定期复制 `backend/data/` 目录
- 正式运营请设置 `DEV_MODE=false` 并配置微信 AppID/Secret
