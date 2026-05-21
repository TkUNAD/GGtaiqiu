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
CORS_ORIGINS=https://你的云托管HTTPS域名
```

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
3. 浏览器访问：`https://你的域名/api/health` 返回 `{"ok":true,...}`
4. 管理后台：`https://你的域名/admin`

## 小程序对接

1. 复制云托管 **HTTPS 公网域名**
2. 修改 `miniprogram/utils/config.js` 正式环境 API 地址
3. 微信公众平台 → 服务器域名 → request 合法域名填入该域名

## 数据说明

业务数据在 `backend/data/*.json`。容器重建可能丢失数据，请定期备份或后续接入 MySQL。
