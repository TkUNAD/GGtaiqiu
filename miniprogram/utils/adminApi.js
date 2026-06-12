const { getApiBaseUrl } = require('./config');
const userApi = require('./api');

function getAppSafe() {
  return getApp();
}

function getAdminAccessToken() {
  const app = getAppSafe();
  return (app && app.globalData.adminAccessToken) || wx.getStorageSync('admin_access_token') || '';
}

function getAdminRefreshToken() {
  const app = getAppSafe();
  return (app && app.globalData.adminRefreshToken) || wx.getStorageSync('admin_refresh_token') || '';
}

function persistAdminTokens(bundle, session) {
  const app = getAppSafe();
  const access = bundle.access_token || '';
  const refresh = bundle.refresh_token || getAdminRefreshToken();
  if (app) {
    if (access) {
      app.globalData.adminAccessToken = access;
    }
    if (bundle.refresh_token) {
      app.globalData.adminRefreshToken = refresh;
    }
    if (session) {
      app.globalData.adminSession = session;
    }
  }
  if (access) {
    wx.setStorageSync('admin_access_token', access);
  }
  if (bundle.refresh_token) {
    wx.setStorageSync('admin_refresh_token', refresh);
  }
  if (session) {
    wx.setStorageSync('admin_session', session);
    if (session.admin_id) {
      wx.setStorageSync('admin_preferred_id', session.admin_id);
    }
  }
}

function getAdminSession() {
  const app = getAppSafe();
  if (app && app.globalData.adminSession) return app.globalData.adminSession;
  return wx.getStorageSync('admin_session') || null;
}

function clearAdminAuth() {
  const app = getAppSafe();
  if (app) {
    app.globalData.adminAccessToken = '';
    app.globalData.adminRefreshToken = '';
    app.globalData.adminSession = null;
  }
  wx.removeStorageSync('admin_access_token');
  wx.removeStorageSync('admin_refresh_token');
  wx.removeStorageSync('admin_session');
}

let _adminRefreshPromise = null;

function tryRefreshAdminToken() {
  if (_adminRefreshPromise) return _adminRefreshPromise;
  const refresh = getAdminRefreshToken();
  if (!refresh) return Promise.reject(new Error('无管理 refresh_token'));
  const app = getAppSafe();
  const baseUrl = (app && app.globalData.baseUrl) || getApiBaseUrl();
  _adminRefreshPromise = new Promise((resolve, reject) => {
    wx.request({
      url: baseUrl + '/api/mp-admin/refresh',
      method: 'POST',
      data: JSON.stringify({ refresh_token: refresh }),
      header: { 'Content-Type': 'application/json' },
      success(res) {
        if (res.data && res.data.code === 0 && res.data.data) {
          const bundle = res.data.data;
          persistAdminTokens(bundle);
          const preferred = wx.getStorageSync('admin_preferred_id') || '';
          if (preferred && getAdminAccessToken()) {
            wx.request({
              url: baseUrl + '/api/mp-admin/me',
              method: 'GET',
              header: {
                'Content-Type': 'application/json',
                'X-Admin-Token': getAdminAccessToken(),
              },
              success(meRes) {
                if (meRes.data && meRes.data.code === 0 && meRes.data.data) {
                  persistAdminTokens({}, meRes.data.data);
                }
                resolve(bundle);
              },
              fail() {
                resolve(bundle);
              },
            });
            return;
          }
          resolve(bundle);
        } else {
          reject((res.data && res.data.msg) || '管理登录已失效');
        }
      },
      fail(err) {
        reject(err.errMsg || '管理登录已失效');
      },
      complete() {
        _adminRefreshPromise = null;
      },
    });
  });
  return _adminRefreshPromise;
}

function adminRequest(url, method = 'GET', data = {}, retried = false, reloginTried = false) {
  const app = getAppSafe();
  const baseUrl = (app && app.globalData.baseUrl) || getApiBaseUrl();
  const upperMethod = (method || 'GET').toUpperCase();
  const useJsonBody = upperMethod === 'POST' || upperMethod === 'PUT' || upperMethod === 'PATCH';
  const token = getAdminAccessToken();

  return new Promise((resolve, reject) => {
    wx.request({
      url: baseUrl + url,
      method: upperMethod,
      data: useJsonBody ? JSON.stringify(data || {}) : data,
      timeout: 15000,
      header: {
        'Content-Type': 'application/json',
        'X-Admin-Token': token,
      },
      success(res) {
        const body = res.data;
        const is401 = res.statusCode === 401 || (body && body.code === 401);
        if (is401 && !retried && url !== '/api/mp-admin/refresh' && url !== '/api/mp-admin/relogin') {
          tryRefreshAdminToken()
            .then(() => adminRequest(url, method, data, true, reloginTried).then(resolve).catch(reject))
            .catch(() => {
              if (!reloginTried) {
                relogin(wx.getStorageSync('admin_preferred_id') || undefined)
                  .then(() => adminRequest(url, method, data, true, true).then(resolve).catch(reject))
                  .catch(() => {
                    clearAdminAuth();
                    reject((res.data && res.data.msg) || '管理登录已失效，请重新登录');
                  });
                return;
              }
              clearAdminAuth();
              reject((res.data && res.data.msg) || '管理登录已失效，请重新登录');
            });
          return;
        }
        if (is401) {
          clearAdminAuth();
          reject((body && body.msg) || '管理登录已失效');
          return;
        }
        if (res.statusCode >= 400) {
          const msg = (body && body.msg) || (typeof body === 'string' ? body : '');
          reject(msg || `请求失败(${res.statusCode})`);
          return;
        }
        if (body && body.code === 0) {
          resolve(body.data);
        } else {
          reject((body && body.msg) || '请求失败');
        }
      },
      fail(err) {
        reject(err.errMsg || '网络错误');
      },
    });
  });
}

function checkEligibility(venueId) {
  let url = '/api/mp-admin/eligibility';
  if (venueId) {
    url += `?venue_id=${encodeURIComponent(venueId)}`;
  }
  return userApi.request(url);
}

function syncBindings(venueId) {
  let url = '/api/mp-admin/sync-bindings';
  if (venueId) {
    url += `?venue_id=${encodeURIComponent(venueId)}`;
  }
  return userApi.request(url, 'POST', {});
}

function applyLoginResult(data) {
  persistAdminTokens(data, data.session);
  return data.session;
}

function scanLogin(token) {
  return userApi.request('/api/mp-admin/scan', 'POST', { token }).then((data) => {
    if (data && data.registered) {
      return { registered: true, message: data.message || '授权成功' };
    }
    return applyLoginResult(data);
  });
}

function relogin(adminId) {
  const body = {};
  const preferred = adminId || wx.getStorageSync('admin_preferred_id') || '';
  if (preferred) body.admin_id = preferred;
  return userApi.request('/api/mp-admin/relogin', 'POST', body).then(applyLoginResult);
}

function switchAdmin(adminId) {
  if (!adminId) return Promise.reject(new Error('请选择管理后台'));
  wx.setStorageSync('admin_preferred_id', adminId);
  const cur = getAdminSession();
  if (cur && cur.admin_id === adminId && getAdminAccessToken()) {
    return Promise.resolve(cur);
  }
  wx.removeStorageSync('admin_access_token');
  wx.removeStorageSync('admin_refresh_token');
  wx.removeStorageSync('admin_session');
  const app = getAppSafe();
  if (app) {
    app.globalData.adminAccessToken = '';
    app.globalData.adminRefreshToken = '';
    app.globalData.adminSession = null;
  }
  return userApi.request('/api/mp-admin/switch', 'POST', { admin_id: adminId }).then(applyLoginResult);
}

function resolveWantedAdminId(expectedAdminId) {
  return (
    expectedAdminId
    || wx.getStorageSync('admin_preferred_id')
    || (getAdminSession() && getAdminSession().admin_id)
    || ''
  );
}

/** 校验并恢复管理登录态；expectedAdminId 为点击入口时要进入的身份 */
async function ensureAdminSession(expectedAdminId) {
  const want = resolveWantedAdminId(expectedAdminId);

  if (getAdminAccessToken()) {
    try {
      const me = await adminRequest('/api/mp-admin/me');
      if (want && me.admin_id && me.admin_id !== want) {
        await switchAdmin(want);
        return getAdminSession();
      }
      persistAdminTokens({}, me);
      return me;
    } catch (e) {
      /* 下方尝试 relogin */
    }
  }
  try {
    const session = await relogin(want || undefined);
    const me = await adminRequest('/api/mp-admin/me');
    if (want && me.admin_id && me.admin_id !== want) {
      await switchAdmin(want);
      return getAdminSession();
    }
    persistAdminTokens({}, me);
    return getAdminSession() || session;
  } catch (e) {
    clearAdminAuth();
    throw e;
  }
}

function fetchMe() {
  return adminRequest('/api/mp-admin/me').then((me) => {
    persistAdminTokens({}, me);
    return me;
  });
}

function logoutAdmin() {
  clearAdminAuth();
}

function hasAdminSession() {
  return !!getAdminAccessToken();
}

function isSuperSetupScene(raw) {
  const s = String(raw || '').trim();
  if (!s) return false;
  if (s.indexOf('sas_') >= 0) return true;
  return /^[a-f0-9]{16}$/i.test(s);
}

function parseQrToken(raw) {
  if (!raw) return '';
  const s = String(raw).trim();
  if (isSuperSetupScene(s)) return '';
  const m = s.match(/adm_([A-Za-z0-9_-]+)/);
  if (m) return m[1];
  if (/^[A-Za-z0-9_-]{20,}$/.test(s)) return s;
  return '';
}

function fetchMenu() {
  return adminRequest('/api/mp-admin/menu');
}

function isSuperSession(session) {
  if (!session) return false;
  return session.role === 'super' || session.console_type === 'super';
}

function superLogin(username, password) {
  return userApi.request('/api/mp-admin/super-login', 'POST', { username, password }).then(applyLoginResult);
}

function bindOwner(username, password) {
  return userApi.request('/api/mp-admin/bind-owner', 'POST', { username, password }).then(applyLoginResult);
}

function canWrite(session) {
  if (!session) return false;
  if (isSuperSession(session)) return true;
  return !!session.is_member_active;
}

function hasPerm(session, key) {
  if (!session) return false;
  if (isSuperSession(session)) return true;
  return !!(session.permissions && session.permissions[key]);
}

module.exports = {
  adminRequest,
  checkEligibility,
  syncBindings,
  scanLogin,
  relogin,
  switchAdmin,
  ensureAdminSession,
  fetchMe,
  fetchMenu,
  isSuperSession,
  superLogin,
  bindOwner,
  logoutAdmin,
  hasAdminSession,
  getAdminSession,
  parseQrToken,
  isSuperSetupScene,
  persistAdminTokens,
  getAdminAccessToken,
  canWrite,
  hasPerm,
};
