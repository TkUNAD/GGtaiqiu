# 微信授权登录说明

本文档整理本项目小程序微信授权登录的完整流程、代码位置与配置方式。

---

## 1. 流程概览

```
用户点击「微信授权登录」(button)
        │
        ├─ 本地有 token ──────────► api.login() ──► GET /api/user/profile（恢复会话）
        │
        ├─ 本机已授权过 ──────────► api.wechatLoginSilent()
        │                              ├─ 读取 wx_last_profile（昵称/头像）
        │                              ├─ wx.login() 获取 code
        │                              └─ POST /api/auth/login { code, nickname, avatar }
        │
        └─ 首次登录 ──────────────► api.wechatLogin()
                                       ├─ wx.requirePrivacyAuthorize（若支持）
                                       ├─ wx.getUserProfile() 弹窗授权
                                       ├─ wx.login() 获取 code
                                       └─ POST /api/auth/login { code, nickname, avatar }

后端 /api/auth/login
        ├─ wx_code_to_openid(code) 调用微信 jscode2session
        ├─ get_or_create_user(openid, nickname, avatar)
        └─ 返回 { token: openid, user }

后续请求 Header: X-Token: <openid>
```

**要点**

- 头像、昵称由**前端** `getUserProfile` 获取，传给后端保存；后端**不再**向微信拉取用户资料。
- 后端仅用 `code` 换取 `openid`（须配置 AppID / AppSecret）。
- 授权过一次后，本机记录 `wx_profile_authorized`，再次登录走静默流程，**不再弹授权窗**（退出登录也不清除该标记）。

---

## 2. 涉及文件

| 层级 | 文件 | 职责 |
|------|------|------|
| 前端 UI | `miniprogram/pages/index/index.wxml` | 登录按钮、授权失败时的头像/昵称备用面板 |
| 前端页面 | `miniprogram/pages/index/index.js` | `onLogin` / `onLogout` / 备用登录 |
| 前端 API | `miniprogram/utils/api.js` | `wechatLogin`、`wechatLoginSilent`、`loginWithProfile`、`login`、`logout` |
| 全局 | `miniprogram/app.js` | 启动时用 token 恢复用户、`setUser` |
| 小程序配置 | `miniprogram/project.config.json` | `appid` |
| 后端路由 | `backend/app.py` | `POST /api/auth/login`、`_user_from_token` |
| 后端服务 | `backend/services.py` | `wx_code_to_openid`、`get_or_create_user` |
| 后端配置 | `backend/config.py` | `WECHAT_APPID`、`WECHAT_SECRET` |
| 密钥 | 项目根目录 `.env`、`wechat.secret.txt` | AppSecret（勿提交 Git） |
| 工具脚本 | `setup-wechat.bat` | 引导填写 AppSecret |

---

## 3. 前端 API（`miniprogram/utils/api.js`）

### 3.1 导出函数

| 函数 | 说明 |
|------|------|
| `wechatLogin()` | 首次登录：隐私协议 → `getUserProfile` → `wx.login` → 提交后端 |
| `wechatLoginSilent()` | 已授权：用缓存昵称头像 + `wx.login`，不弹授权窗 |
| `loginWithProfile(nickname, avatar)` | 仅 `wx.login` + `POST /api/auth/login` |
| `login()` | 用本地 `token` 请求 `/api/user/profile` 恢复会话；失败且已授权则静默重登 |
| `logout()` | 清除 `token`、`user`；**保留**授权标记与上次头像昵称 |
| `hasWxProfileAuthorized()` | 是否本机已授权过 |
| `markWxProfileAuthorized()` | 标记已授权 |

### 3.2 本地存储

| Key | 内容 |
|-----|------|
| `token` | 登录态，值为用户 `openid` |
| `user` | 用户信息对象 |
| `wx_profile_authorized` | `true` 表示已授权过 |
| `wx_last_profile` | `{ nickname, avatar }`，供静默登录 |

### 3.3 请求头

所有需登录接口自动携带：

```
X-Token: <globalData.token>
```

---

## 4. 首页逻辑（`miniprogram/pages/index/index.js`）

```javascript
onLogin() {
  if (wx.getStorageSync('token')) {
    api.login().then(onSuccess).catch(onFail);
    return;
  }
  if (api.hasWxProfileAuthorized()) {
    api.wechatLoginSilent().then(onSuccess).catch(onFail);
    return;
  }
  api.wechatLogin().then(onSuccess).catch(onFail);
}
```

`getUserProfile` 不可用时，展示备用面板：`chooseAvatar` + `type="nickname"` → `api.loginWithProfile`。

---

## 5. 后端接口

### 5.1 登录

**POST** `/api/auth/login`

请求体：

```json
{
  "code": "wx.login 返回的临时凭证",
  "nickname": "微信昵称",
  "avatar": "微信头像 URL"
}
```

响应（`code === 0`）：

```json
{
  "data": {
    "token": "openid",
    "user": {
      "id": "U...",
      "nickname": "...",
      "avatar": "...",
      "score": 1000,
      "tier": { "tier_name": "...", "star": 1 },
      "rank": 1
    }
  }
}
```

校验：

- 缺少 `code` → 错误
- 缺少 `nickname` → 400
- 未配置 AppSecret → 微信换 openid 失败

### 5.2 鉴权

```python
def _user_from_token():
    token = request.headers.get("X-Token") or request.args.get("token")
    return next((u for u in users if u.get("openid") == token), None)
```

### 5.3 微信 code 换 openid（`services.wx_code_to_openid`）

```
GET https://api.weixin.qq.com/sns/jscode2session
  ?appid=WECHAT_APPID
  &secret=WECHAT_SECRET
  &js_code=code
  &grant_type=authorization_code
```

---

## 6. 配置步骤

1. 微信公众平台获取 **AppID**、**AppSecret**（开发 → 开发管理 → 开发设置）。
2. 双击运行项目根目录 **`setup-wechat.bat`**，在 `wechat.secret.txt` 单独一行粘贴 AppSecret。
3. 或在 `.env` 中设置：
   ```
   WECHAT_APPID=你的AppID
   WECHAT_SECRET=你的AppSecret
   DEV_MODE=false
   ```
4. `miniprogram/project.config.json` 中 `appid` 与 AppID 一致。
5. 重启 **`run.bat`**，访问 `http://127.0.0.1:5000/api/health`，确认 `wechat_ready: true`。
6. 微信开发者工具：本地设置勾选「不校验合法域名」；真机调试时 `config.js` 填写电脑局域网 IP。

**打开项目方式（二选一）：**

- 打开整个仓库根目录 `weixin_xiaochengxu_1(20260518)`（根目录 `project.config.json` 已设置 `miniprogramRoot: miniprogram/`）
- 或只打开子目录 **`miniprogram`**

若报错「在项目根目录未找到 app.json」，说明打开了错误目录，或未识别 `miniprogramRoot`，请关闭项目后重新导入。

---

## 7. 常见问题

| 现象 | 处理 |
|------|------|
| 网络未连接 / ERR_CONNECTION_REFUSED | 先启动 `run.bat`，保持窗口不关 |
| 未配置 AppID/Secret | 填写 `wechat.secret.txt` 后重启后端 |
| 不弹授权窗但自动登录 | 已授权过，属正常；清缓存或删 `wx_profile_authorized` 可重新授权 |
| getUserProfile 失败 | 使用首页备用面板手动选头像、填昵称 |
| 登录成功但昵称是「球友xxxx」 | 旧逻辑未传昵称；重新授权登录或「我的」页修改昵称 |

---

## 8. 相关代码索引（行号供跳转，以实际文件为准）

- 前端核心：`miniprogram/utils/api.js` — `WX_PROFILE_AUTH_KEY` 起
- 首页入口：`miniprogram/pages/index/index.js` — `onLogin`
- 后端登录：`backend/app.py` — `auth_login`
- 换 openid：`backend/services.py` — `wx_code_to_openid`
