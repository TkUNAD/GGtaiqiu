const api = require('./api');

function requireTermsAgreed(page) {
  if (page.data.agreedToTerms) return true;
  wx.showToast({ title: '请先阅读并同意相关协议', icon: 'none', duration: 2500 });
  return false;
}

function attachLoginHandlers(page, onSuccessExtra) {
  page.onToggleAgree = function onToggleAgree() {
    page.setData({ agreedToTerms: !page.data.agreedToTerms });
  };

  page.openAgreement = function openAgreement(e) {
    const type = (e.currentTarget && e.currentTarget.dataset.type) || 'user';
    wx.navigateTo({ url: `/pages/agreement/agreement?type=${type}` });
  };

  page.openLegal = page.openAgreement;

  page.onLogin = function onLogin() {
    if (page.data.logging) return;
    if (!requireTermsAgreed(page)) return;
    page.setData({ logging: true, showAuthFallback: false });

    const onSuccess = () => {
      const app = getApp();
      page.setData({
        user: app.globalData.user,
        logging: false,
        showAuthFallback: false,
        pendingNickname: '',
        pendingAvatar: '',
      });
      wx.showToast({ title: '登录成功', icon: 'success' });
      if (typeof onSuccessExtra === 'function') {
        return onSuccessExtra.call(page);
      }
    };

    const onFail = (e) => {
      const msg = typeof e === 'string' ? e : '登录失败';
      const useFallback = msg.indexOf('getUserProfile') >= 0
        || msg.indexOf('不支持') >= 0
        || msg.indexOf('隐私') >= 0;
      page.setData({ logging: false, showAuthFallback: useFallback });
      if (!useFallback) {
        const secretHint = msg.indexOf('AppSecret') >= 0 || msg.indexOf('Secret') >= 0
          ? '\n\n请配置微信 AppSecret 后重启后端。'
          : '\n\n请确认后端已启动（run.bat）。';
        wx.showModal({ title: '登录失败', content: msg + secretHint, showCancel: false });
      } else {
        wx.showToast({ title: '请选择头像并填写昵称', icon: 'none', duration: 2500 });
      }
    };

    if (wx.getStorageSync('token')) {
      api.login().then(onSuccess).catch(onFail);
      return;
    }
    if (api.hasWxProfileAuthorized()) {
      api.wechatLoginSilent().then(onSuccess).catch(onFail);
      return;
    }
    api.wechatLogin().then(onSuccess).catch(onFail);
  };

  page.onChooseAvatar = function onChooseAvatar(e) {
    const url = e.detail && e.detail.avatarUrl;
    if (url) page.setData({ pendingAvatar: url });
  };

  page.onNicknameInput = function onNicknameInput(e) {
    page.setData({ pendingNickname: (e.detail && e.detail.value) || '' });
  };

  page.onConfirmProfileLogin = function onConfirmProfileLogin() {
    if (!requireTermsAgreed(page)) return;
    const nickname = (page.data.pendingNickname || '').trim();
    const avatar = (page.data.pendingAvatar || '').trim();
    if (!nickname) {
      wx.showToast({ title: '请先填写微信昵称', icon: 'none' });
      return;
    }
    if (page.data.logging) return;
    page.setData({ logging: true });
    api.loginWithProfile(nickname, avatar)
      .then(() => {
        const app = getApp();
        page.setData({
          user: app.globalData.user,
          logging: false,
          showAuthFallback: false,
        });
        wx.showToast({ title: '登录成功', icon: 'success' });
        if (typeof onSuccessExtra === 'function') {
          return onSuccessExtra.call(page);
        }
      })
      .catch((e) => {
        page.setData({ logging: false });
        wx.showModal({ title: '登录失败', content: String(e), showCancel: false });
      });
  };

  page.onLogout = function onLogout() {
    api.logout();
    page.setData({
      user: null,
      profile: null,
      showAuthFallback: false,
      pendingNickname: '',
      pendingAvatar: '',
      agreedToTerms: false,
    });
    wx.showToast({ title: '已退出', icon: 'none' });
  };
}

module.exports = { attachLoginHandlers };
