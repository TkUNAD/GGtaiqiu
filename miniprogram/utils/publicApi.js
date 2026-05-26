const { getApiBaseUrl } = require('./config');

function getBase() {
  const app = getApp();
  return (app && app.globalData.baseUrl) || getApiBaseUrl();
}

function publicRequest(url, method = 'GET', data = {}) {
  const upper = (method || 'GET').toUpperCase();
  const useBody = upper === 'POST' || upper === 'PUT';
  return new Promise((resolve, reject) => {
    wx.request({
      url: getBase() + url,
      method: upper,
      data: useBody ? JSON.stringify(data || {}) : data,
      header: { 'Content-Type': 'application/json' },
      success(res) {
        if (res.data && res.data.code === 0) {
          resolve(res.data.data);
        } else {
          reject((res.data && res.data.msg) || '请求失败');
        }
      },
      fail(err) {
        reject(err.errMsg || '网络错误');
      },
    });
  });
}

module.exports = {
  getSuperSetupStatus: () => publicRequest('/api/public/super-setup/status'),
  getCaptcha: () => publicRequest('/api/public/captcha'),
  submitApply: (body) => publicRequest('/api/public/venue-apply/submit', 'POST', body),
  sendResetCode: (phone) => publicRequest('/api/public/venue-reset/send-code', 'POST', { phone }),
  resetPassword: (body) => publicRequest('/api/public/venue-reset/confirm', 'POST', body),
  verifySuperToken: (token) => publicRequest('/api/public/super-setup/verify', 'POST', { token }),
  completeSuperSetup: (body) => publicRequest('/api/public/super-setup/complete', 'POST', body),
};
