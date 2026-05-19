const { getApiBaseUrl } = require('./config');



function getAppSafe() {

  return getApp();

}



function request(url, method = 'GET', data = {}) {

  const app = getAppSafe();

  const baseUrl = (app && app.globalData.baseUrl) || getApiBaseUrl();

  const upperMethod = (method || 'GET').toUpperCase();

  const useJsonBody = upperMethod === 'POST' || upperMethod === 'PUT' || upperMethod === 'PATCH';



  return new Promise((resolve, reject) => {

    wx.request({

      url: baseUrl + url,

      method: upperMethod,

      data: useJsonBody ? JSON.stringify(data || {}) : data,

      timeout: 15000,

      header: {

        'Content-Type': 'application/json',

        'X-Token': (app && app.globalData.token) || '',

      },

      success(res) {

        if (res.statusCode === 401 || (res.data && res.data.code === 401)) {

          logout();

          reject((res.data && res.data.msg) || '登录已失效，请重新登录');

          return;

        }

        if (res.statusCode >= 400) {

          const msg = (res.data && res.data.msg) || `请求失败(${res.statusCode})`;

          reject(msg);

          return;

        }

        if (res.data && res.data.code === 0) {

          resolve(res.data.data);

        } else {

          const msg = (res.data && res.data.msg) || '请求失败';

          if (res.data && res.data.code === 401) {
            logout();
          }

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



/** 开发测试：固定账号登录（选手A/B 各一台设备点一次即可） */

function loginAsTest(code, nickname) {

  return new Promise((resolve, reject) => {

    wx.showLoading({ title: '登录中...', mask: true });

    request('/api/auth/login', 'POST', { code, nickname })

      .then((data) => {

        const app = getAppSafe();

        if (app) app.setUser(data.user, data.token);

        wx.hideLoading();

        resolve(data);

      })

      .catch((err) => {

        wx.hideLoading();

        reject(err);

      });

  });

}



const WX_PROFILE_AUTH_KEY = 'wx_profile_authorized';

function markWxProfileAuthorized() {
  wx.setStorageSync(WX_PROFILE_AUTH_KEY, true);
}

function hasWxProfileAuthorized() {
  return !!wx.getStorageSync(WX_PROFILE_AUTH_KEY);
}

function notifyPagesAuthChange() {
  try {
    getCurrentPages().forEach((p) => {
      if (p && typeof p.onShow === 'function') {
        p.onShow();
      }
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

  }

  wx.removeStorageSync('token');

  wx.removeStorageSync('user');

  notifyPagesAuthChange();

  // 保留 wx_profile_authorized，同一微信再次登录无需重复弹授权窗

}



/** 仅 wx.login + 后端换 openid（不含头像昵称授权，供已配置正式 AppID 时内部复用） */
function loginWithWxCode(nickname, avatar) {
  return new Promise((resolve, reject) => {
    wx.showLoading({ title: '登录中...', mask: true });
    wx.login({
      success(loginRes) {
        if (!loginRes.code) {
          wx.hideLoading();
          reject('获取微信登录码失败');
          return;
        }
        request('/api/auth/login', 'POST', {
          code: loginRes.code,
          nickname: nickname || '',
          avatar: avatar || '',
        })
          .then((data) => {
            const app = getAppSafe();
            if (app) app.setUser(data.user, data.token);
            wx.hideLoading();
            resolve(data);
          })
          .catch((err) => {
            wx.hideLoading();
            reject(err);
          });
      },
      fail(err) {
        wx.hideLoading();
        reject(err.errMsg || '微信登录失败');
      },
    });
  });
}

/**
 * 微信授权登录：首次须授权昵称头像；同一设备已授权过则静默 wx.login
 */
function login() {
  return new Promise((resolve, reject) => {
    const app = getAppSafe();
    const cachedToken = wx.getStorageSync('token');

    const finishLogin = (nickname, avatar) => {
      loginWithWxCode(nickname, avatar)
        .then((data) => {
          markWxProfileAuthorized();
          resolve(data);
        })
        .catch(reject);
    };

    // 本地仍有 token，尝试恢复会话
    if (cachedToken) {
      if (app && !app.globalData.token) {
        app.globalData.token = cachedToken;
      }
      wx.showLoading({ title: '登录中...', mask: true });
      request('/api/user/profile')
        .then((profile) => {
          const u = { ...profile.user, tier: profile.tier, rank: profile.rank };
          if (app) app.setUser(u, cachedToken);
          wx.hideLoading();
          resolve({ user: u, token: cachedToken });
        })
        .catch(() => {
          wx.hideLoading();
          if (app) {
            app.globalData.token = '';
            app.globalData.user = null;
          }
          wx.removeStorageSync('token');
          wx.removeStorageSync('user');
          if (hasWxProfileAuthorized()) {
            finishLogin('', '');
          } else {
            requestUserProfile(finishLogin, reject);
          }
        });
      return;
    }

    // 此前已在本机完成过微信资料授权，静默登录
    if (hasWxProfileAuthorized()) {
      finishLogin('', '');
      return;
    }

    requestUserProfile(finishLogin, reject);
  });
}

function requestUserProfile(onOk, onErr) {
  if (typeof wx.getUserProfile === 'function') {
    wx.getUserProfile({
      desc: '用于展示昵称、头像并参与天梯对战',
      success(res) {
        const u = (res && res.userInfo) || {};
        onOk(u.nickName || '', u.avatarUrl || '');
      },
      fail(err) {
        const msg = (err && err.errMsg) || '';
        if (msg.indexOf('deny') >= 0 || msg.indexOf('cancel') >= 0) {
          onErr('您已拒绝授权，无法登录');
        } else {
          onErr('需要授权微信昵称与头像后才能登录');
        }
      },
    });
    return;
  }

  wx.showModal({
    title: '微信授权登录',
    content: '将使用您的微信账号登录并记录对战数据，是否继续？',
    confirmText: '授权登录',
    cancelText: '取消',
    success(r) {
      if (r.confirm) onOk('', '');
      else onErr('已取消登录');
    },
  });
}



function ping() {

  return request('/api/health');

}



module.exports = { request, login, loginWithWxCode, loginAsTest, logout, ping };

