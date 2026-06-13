const { getApiBaseUrl } = require('./config');
const { readLocalAvatarBase64, isEphemeralAvatar, resolveDisplayAvatar, DEFAULT_AVATAR } = require('./avatar');

function getAppSafe() {
  return getApp();
}

function getAccessToken() {
  const app = getAppSafe();
  return (app && app.globalData.accessToken) || wx.getStorageSync('access_token') || '';
}

function getRefreshToken() {
  const app = getAppSafe();
  return (app && app.globalData.refreshToken) || wx.getStorageSync('refresh_token') || '';
}

function persistTokens(bundle) {
  const app = getAppSafe();
  const access = bundle.access_token || '';
  const refresh = bundle.refresh_token || getRefreshToken();
  if (app) {
    app.globalData.accessToken = access;
    app.globalData.token = access;
    if (bundle.refresh_token) {
      app.globalData.refreshToken = bundle.refresh_token;
    }
  }
  wx.setStorageSync('access_token', access);
  wx.setStorageSync('token', access);
  if (bundle.refresh_token) {
    wx.setStorageSync('refresh_token', bundle.refresh_token);
  }
}

let _refreshPromise = null;

function tryRefreshToken() {
  if (_refreshPromise) return _refreshPromise;
  const refresh = getRefreshToken();
  if (!refresh) {
    return Promise.reject(new Error('无 refresh_token'));
  }
  const app = getAppSafe();
  const baseUrl = (app && app.globalData.baseUrl) || getApiBaseUrl();
  _refreshPromise = new Promise((resolve, reject) => {
    wx.request({
      url: baseUrl + '/api/auth/refresh',
      method: 'POST',
      data: JSON.stringify({ refresh_token: refresh }),
      header: { 'Content-Type': 'application/json' },
      success(res) {
        if (res.data && res.data.code === 0 && res.data.data) {
          persistTokens(res.data.data);
          resolve(res.data.data);
        } else {
          reject((res.data && res.data.msg) || '刷新登录失败');
        }
      },
      fail(err) {
        reject(err.errMsg || '刷新登录失败');
      },
      complete() {
        _refreshPromise = null;
      },
    });
  });
  return _refreshPromise;
}

function parseResponseBody(raw) {
  if (raw && typeof raw === 'object') return raw;
  if (typeof raw === 'string') {
    const text = raw.trim();
    if (!text) return null;
    if (text.charAt(0) === '{' || text.charAt(0) === '[') {
      try {
        return JSON.parse(text);
      } catch (e) {
        return null;
      }
    }
  }
  return null;
}

function responseErrorMessage(res) {
  const body = parseResponseBody(res.data);
  if (body && body.msg) return body.msg;
  if (res.statusCode === 404) return '接口不存在，请更新后端服务后重试';
  if (res.statusCode >= 500) return `服务器错误(${res.statusCode})，请稍后重试`;
  if (res.statusCode >= 400) return `请求失败(${res.statusCode})`;
  return '请求失败';
}

function request(url, method = 'GET', data = {}, retried = false) {
  const app = getAppSafe();
  const baseUrl = (app && app.globalData.baseUrl) || getApiBaseUrl();
  const upperMethod = (method || 'GET').toUpperCase();
  const useJsonBody = upperMethod === 'POST' || upperMethod === 'PUT' || upperMethod === 'PATCH';
  const token = getAccessToken();
  const reqData = useJsonBody
    ? JSON.stringify(data || {})
    : (data && Object.keys(data).length ? data : undefined);

  return new Promise((resolve, reject) => {
    wx.request({
      url: baseUrl + url,
      method: upperMethod,
      data: reqData,
      timeout: 15000,
      header: {
        'Content-Type': 'application/json',
        Authorization: token ? `Bearer ${token}` : '',
        'X-Token': token,
      },
      success(res) {
        const body = parseResponseBody(res.data);
        const is401 = res.statusCode === 401 || (body && body.code === 401);
        if (is401 && !retried && url !== '/api/auth/refresh') {
          tryRefreshToken()
            .then(() => request(url, method, data, true).then(resolve).catch(reject))
            .catch(() => {
              logout();
              reject((body && body.msg) || '登录已失效，请重新登录');
            });
          return;
        }
        if (is401) {
          logout();
          reject((body && body.msg) || '登录已失效，请重新登录');
          return;
        }
        if (res.statusCode >= 400) {
          reject(responseErrorMessage(res));
          return;
        }
        if (body && body.code === 0) {
          resolve(body.data);
        } else {
          const msg = responseErrorMessage(res);
          if (body && body.code === 401) logout();
          reject(msg);
        }
      },
      fail(err) {
        let msg = err.errMsg || '网络错误';
        if (msg.indexOf('CONNECTION_REFUSED') >= 0 || msg.indexOf('timeout') >= 0) {
          msg = '无法连接服务器，请确认：①后端已启动 ②手机与电脑同一WiFi ③config.js中IP正确';
        }
        reject(msg);
      },
    });
  });
}

const WX_PROFILE_AUTH_KEY = 'wx_profile_authorized';
const WX_LAST_PROFILE_KEY = 'wx_last_profile';

function markWxProfileAuthorized() {
  wx.setStorageSync(WX_PROFILE_AUTH_KEY, true);
}

function hasWxProfileAuthorized() {
  return !!wx.getStorageSync(WX_PROFILE_AUTH_KEY);
}

function normalizeUserAvatar(user) {
  if (!user) return user;
  return {
    ...user,
    avatar: resolveDisplayAvatar(user.avatar),
  };
}

function saveLastProfile(user) {
  if (!user || !user.nickname) return;
  const av = (user.avatar || '').trim();
  const storedAv = av && av !== DEFAULT_AVATAR && !av.startsWith('/assets/') ? av : '';
  wx.setStorageSync(WX_LAST_PROFILE_KEY, {
    nickname: user.nickname,
    avatar: storedAv,
  });
}

function getLastProfile() {
  return wx.getStorageSync(WX_LAST_PROFILE_KEY) || {};
}

function notifyPagesAuthChange() {
  try {
    getCurrentPages().forEach((p) => {
      if (p && typeof p.onShow === 'function') p.onShow();
    });
  } catch (e) {
    /* ignore */
  }
}

function logout() {
  const app = getAppSafe();
  if (app) {
    app.globalData.user = null;
    app.globalData.token = '';
    app.globalData.accessToken = '';
    app.globalData.refreshToken = '';
  }
  wx.removeStorageSync('access_token');
  wx.removeStorageSync('refresh_token');
  wx.removeStorageSync('token');
  wx.removeStorageSync('user');
  notifyPagesAuthChange();
}

function loginWithProfile(nickname, avatar) {
  return new Promise((resolve, reject) => {
    const nick = (nickname || '').trim();
    if (!nick) {
      reject('请先授权微信昵称');
      return;
    }
    const av = (avatar || '').trim();
    const prepareBody = (avatarBase64) => {
      const body = { code: '', nickname: nick, avatar: av };
      if (avatarBase64) {
        body.avatar_base64 = avatarBase64;
        if (isEphemeralAvatar(av)) body.avatar = '';
      }
      return body;
    };
    wx.login({
      success(loginRes) {
        if (!loginRes.code) {
          reject('获取微信登录码失败');
          return;
        }
        wx.showLoading({ title: '登录中...', mask: true });
        const sendLogin = (body) => {
          body.code = loginRes.code;
          request('/api/auth/login', 'POST', body)
            .then((data) => {
              const app = getAppSafe();
              persistTokens(data);
              const user = normalizeUserAvatar(data.user);
              if (app) app.setUser(user, data.access_token, data.refresh_token);
              saveLastProfile(user);
              markWxProfileAuthorized();
              wx.hideLoading();
              resolve(data);
            })
            .catch((err) => {
              wx.hideLoading();
              reject(err);
            });
        };
        if (av && isEphemeralAvatar(av)) {
          readLocalAvatarBase64(av).then((b64) => {
            if (!b64) {
              wx.hideLoading();
              reject('头像读取失败，请重新选择头像后登录');
              return;
            }
            sendLogin(prepareBody(b64));
          });
        } else {
          sendLogin(prepareBody(''));
        }
      },
      fail(err) {
        reject(err.errMsg || '微信登录失败');
      },
    });
  });
}

function _getUserProfile() {
  return new Promise((resolve, reject) => {
    if (typeof wx.getUserProfile !== 'function') {
      reject('getUserProfile: 当前基础库不支持');
      return;
    }
    wx.getUserProfile({
      desc: '用于展示昵称、头像并参与天梯对战',
      success(res) {
        const u = (res && res.userInfo) || {};
        const nickname = (u.nickName || '').trim();
        const avatar = (u.avatarUrl || '').trim();
        if (!nickname) {
          reject('未获取到微信昵称');
          return;
        }
        resolve({ nickname, avatar });
      },
      fail(err) {
        const msg = (err && err.errMsg) || '';
        if (msg.indexOf('deny') >= 0 || msg.indexOf('cancel') >= 0) {
          reject('您已拒绝授权，无法登录');
          return;
        }
        reject(msg || '需要授权微信昵称与头像后才能登录');
      },
    });
  });
}

function wechatLoginSilent() {
  const last = getLastProfile();
  const nickname = (last.nickname || '').trim();
  const avatar = (last.avatar || '').trim();
  if (!nickname) return wechatLogin();
  return loginWithProfile(nickname, avatar);
}

function wechatLogin() {
  return new Promise((resolve, reject) => {
    const start = () => {
      _getUserProfile()
        .then(({ nickname, avatar }) => loginWithProfile(nickname, avatar))
        .then(resolve)
        .catch(reject);
    };
    if (typeof wx.requirePrivacyAuthorize === 'function') {
      wx.requirePrivacyAuthorize({
        success: start,
        fail: () => reject('请先同意用户隐私保护指引'),
      });
      return;
    }
    start();
  });
}

function login() {
  return new Promise((resolve, reject) => {
    const app = getAppSafe();
    const access = getAccessToken();
    const refresh = getRefreshToken();
    if (!access && !refresh) {
      reject('请点击「微信授权登录」完成授权');
      return;
    }
    const doProfile = (token) => {
      if (app && !app.globalData.accessToken) {
        app.globalData.accessToken = token;
        app.globalData.token = token;
      }
      wx.showLoading({ title: '登录中...', mask: true });
      request('/api/user/profile')
        .then((profile) => {
          const u = normalizeUserAvatar({
            ...profile.user,
            tier: profile.tier,
            rank: profile.rank,
          });
          if (app) app.setUser(u, token, refresh);
          saveLastProfile(u);
          markWxProfileAuthorized();
          wx.hideLoading();
          resolve({ user: u, access_token: token, refresh_token: refresh });
        })
        .catch(() => {
          wx.hideLoading();
          if (refresh) {
            tryRefreshToken()
              .then((bundle) => doProfile(bundle.access_token).then(resolve).catch(reject))
              .catch(() => {
                logout();
                if (hasWxProfileAuthorized()) {
                  wechatLoginSilent().then(resolve).catch(reject);
                  return;
                }
                reject('登录已过期，请重新点击「微信授权登录」');
              });
            return;
          }
          logout();
          reject('登录已过期，请重新点击「微信授权登录」');
        });
    };
    if (access) {
      doProfile(access);
    } else if (refresh) {
      tryRefreshToken()
        .then((bundle) => doProfile(bundle.access_token))
        .then(resolve)
        .catch(reject);
    }
  });
}

function ping() {
  return request('/api/health');
}

function updateAvatar(avatar) {
  const av = (avatar || '').trim();
  const send = (avatarBase64) => {
    const body = { avatar: av };
    if (avatarBase64) {
      body.avatar_base64 = avatarBase64;
      if (isEphemeralAvatar(av)) body.avatar = '';
    }
    return request('/api/user/avatar', 'POST', body);
  };
  if (isEphemeralAvatar(av)) {
    return readLocalAvatarBase64(av).then((b64) => send(b64));
  }
  return send('');
}

module.exports = {
  request,
  login,
  wechatLogin,
  wechatLoginSilent,
  loginWithProfile,
  logout,
  ping,
  updateAvatar,
  hasWxProfileAuthorized,
  markWxProfileAuthorized,
  tryRefreshToken,
};
