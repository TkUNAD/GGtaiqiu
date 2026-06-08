# 微信云托管部署说明

## 发布前检查（最常见失败原因）

| 检查项 | 说明 |
|--------|------|
| **端口** | 控制台「端口」填 **80**，与 `Dockerfile` 中 `EXPOSE 80`、`ENV PORT=80` 一致 |
| **Dockerfile** | 必须在**项目根目录**，上传/拉取的是整个仓库根目录 |
| **环境变量** | 见下表；未配置时容器可能启动失败或反复重启 |
| **构建日志** | 版本详情 → 构建日志：看 pip 是否失败 |
| **运行日志** | 版本详情 → 运行日志：看是否 `RuntimeError`、端口错误 |

## 服务设置 → 环境变量（生产建议）

在云托管控制台 **服务设置 → 环境变量** 添加（不要写进 Git）：

```
PORT=80
HOST=0.0.0.0
DEV_MODE=false
FLASK_DEBUG=false
SECRET_KEY=随机长字符串A
JWT_SECRET=随机长字符串B
ADMIN_USER=admin
ADMIN_PASS=强密码
WECHAT_APPID=你的小程序AppID
WECHAT_SECRET=你的小程序AppSecret
PUBLIC_URL=https://ggtaiqiu.com
CORS_ORIGINS=https://ggtaiqiu.com
MYSQL_HOST=10.4.106.26
MYSQL_PORT=3306
MYSQL_USER=ggtaiqiu_app
MYSQL_PASSWORD=你的密码
MYSQL_DATABASE=ggtaiqiu
```

配置 `MYSQL_*` 后，后端自动使用 MySQL（`app_collections` 表存 JSON 集合）。首次启动若库为空，会从 `backend/data/*.json` 自动导入。

生成随机密钥示例（本地 PowerShell）：

```powershell
[Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Maximum 256 }))
```

## 部署方式

### 推荐：从 GitHub 拉取

1. 新建版本 → **从代码库拉取** → 授权 GitHub
2. 仓库：`TkUNAD/GGtaiqiu`，分支 `main`
3. 构建目录：留空（根目录）
4. 端口：**80**
5. 发布并 **开启 100% 流量**

### 手动上传 zip

- 勿包含 `backend/venv`、`.env`、`wechat.secret.txt`
- 须含根目录 `Dockerfile`
- 单包不超过 2MB（本仓库约 0.5MB，一般足够）

## 验证是否成功

1. 构建状态为 **成功**
2. 实例为 **运行中**（非 CrashLoopBackOff）
3. 浏览器访问：`https://ggtaiqiu.com/api/health` 返回 `status: ok`，且 `storage.backend` 为 `mysql`、`mysql.ok` 为 `true`
4. DMC 中 `ggtaiqiu` 库应有表 **`app_collections`**（数据以 JSON 文档存储，不是 users/matches 分表）
5. 管理后台：`https://ggtaiqiu.com/admin`

## 小程序对接

1. 确保域名 `ggtaiqiu.com` 已解析并开启 HTTPS
2. `miniprogram/utils/config.js` 中 `PROD_API` 已设为 `https://ggtaiqiu.com`
3. 微信公众平台 → 服务器域名 → request 合法域名填入 `ggtaiqiu.com`

## 数据说明

已配置 `MYSQL_*` 时，业务数据写入 MySQL 表 `app_collections`；未配置时仍使用 `backend/data/*.json`。可手动执行 `python backend/scripts/migrate_json_to_mysql.py` 导入历史 JSON。
