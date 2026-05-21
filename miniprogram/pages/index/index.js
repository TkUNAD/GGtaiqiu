const api = require('../../utils/api');
const { getApiBaseUrl } = require('../../utils/config');
const { withRankIcons } = require('../../utils/rank');

Page({
  data: {
    user: null,
    topRank: [],
    tables: [],
    challengeTargets: [],
    netError: '',
    apiUrl: '',
    logging: false,
    showAuthFallback: false,
    pendingNickname: '',
    pendingAvatar: '',
  },

  onShow() {
    const app = getApp();
    this.setData({
      user: app.globalData.user,
      apiUrl: app.globalData.baseUrl || getApiBaseUrl(),
    });
    this.loadData();
  },

  retryNetwork() {
    const app = getApp();
    app.globalData.baseUrl = getApiBaseUrl();
    this.setData({ apiUrl: app.globalData.baseUrl, netError: '' });
    this.loadData();
  },

  ensureLogin() {
    if (!getApp().globalData.token) {
      wx.showToast({ title: '请先点击下方「微信授权登录」', icon: 'none', duration: 2500 });
      return Promise.resolve(false);
    }
    return Promise.resolve(true);
  },

  loadData() {
    const self = this;
    return api.ping()
      .then(() => {
        self.setData({ netError: '' });
        const { VENUE_ID } = require('../../utils/config');
        return api.request('/api/rank/list?limit=5')
          .then((list) => {
            const topRank = withRankIcons(list);
            const tablesUrl = '/api/tables' + (VENUE_ID ? `?venue_id=${VENUE_ID}` : '');
            return api.request(tablesUrl).then((tables) => {
              self.setData({ topRank, tables });
            });
          })
          .catch((e) => {
            console.error('[loadData] rank/tables', e);
            wx.showToast({ title: '排行或桌台加载失败', icon: 'none' });
          });
      })
      .catch((e) => {
        const msg = typeof e === 'string' ? e : '网络连接失败';
        self.setData({ netError: msg });
      })
      .then(() => self.loadChallengeTargets());
  },

  loadChallengeTargets() {
    const app = getApp();
    const token = app.globalData.token || wx.getStorageSync('token');
    if (!token) {
      this.setData({ challengeTargets: [] });
      return Promise.resolve();
    }
    return api.request('/api/rank/challenge-targets')
      .then((ch) => {
        this.setData({ challengeTargets: (ch && ch.targets) || [] });
      })
      .catch((e) => {
        const msg = String(e || '');
        console.error('[loadData] challenge', e);
        this.setData({ challengeTargets: [] });
        if (msg.indexOf('登录') >= 0 || msg.indexOf('401') >= 0) {
          return;
        }
        wx.showToast({ title: '挑战列表加载失败', icon: 'none' });
      });
  },

  onLogout() {
    api.logout();
    this.setData({
      user: null,
      challengeTargets: [],
      showAuthFallback: false,
      pendingNickname: '',
      pendingAvatar: '',
    });
    wx.showToast({ title: '已退出', icon: 'none' });
  },

  onLogin() {
    if (this.data.logging) return;
    this.setData({ logging: true, showAuthFallback: false });

    const onSuccess = () => {
      const app = getApp();
      this.setData({
        user: app.globalData.user,
        netError: '',
        logging: false,
        showAuthFallback: false,
        pendingNickname: '',
        pendingAvatar: '',
      });
      wx.showToast({ title: '登录成功', icon: 'success' });
      return this.loadData();
    };

    const onFail = (e) => {
      const msg = typeof e === 'string' ? e : '登录失败';
      const useFallback = msg.indexOf('getUserProfile') >= 0
        || msg.indexOf('不支持') >= 0
        || msg.indexOf('隐私') >= 0;
      this.setData({
        logging: false,
        showAuthFallback: useFallback,
      });
      if (!useFallback) {
        const secretHint = msg.indexOf('AppSecret') >= 0 || msg.indexOf('Secret') >= 0
          ? '\n\n请双击运行项目根目录 setup-wechat.bat，在 wechat.secret.txt 粘贴 AppSecret 后重启 run.bat。'
          : '\n\n请确认后端已启动（run.bat）。';
        wx.showModal({
          title: '登录失败',
          content: msg + secretHint,
          showCancel: false,
        });
      } else {
        wx.showToast({ title: '请在下方面板选择头像并填写昵称', icon: 'none', duration: 2500 });
      }
    };

    // 有 token：直接恢复会话
    if (wx.getStorageSync('token')) {
      api.login().then(onSuccess).catch(onFail);
      return;
    }
    // 本机已授权过：静默登录，不再弹授权窗
    if (api.hasWxProfileAuthorized()) {
      api.wechatLoginSilent().then(onSuccess).catch(onFail);
      return;
    }
    // 首次：弹出微信授权窗
    api.wechatLogin().then(onSuccess).catch(onFail);
  },

  onChooseAvatar(e) {
    const url = e.detail && e.detail.avatarUrl;
    if (url) this.setData({ pendingAvatar: url });
  },

  onNicknameInput(e) {
    this.setData({ pendingNickname: (e.detail && e.detail.value) || '' });
  },

  onConfirmProfileLogin() {
    const nickname = (this.data.pendingNickname || '').trim();
    const avatar = (this.data.pendingAvatar || '').trim();
    if (!nickname) {
      wx.showToast({ title: '请先填写微信昵称', icon: 'none' });
      return;
    }
    if (this.data.logging) return;
    this.setData({ logging: true });
    api.loginWithProfile(nickname, avatar)
      .then(() => {
        const app = getApp();
        this.setData({
          user: app.globalData.user,
          logging: false,
          showAuthFallback: false,
        });
        wx.showToast({ title: '登录成功', icon: 'success' });
        return this.loadData();
      })
      .catch((e) => {
        this.setData({ logging: false });
        wx.showModal({
          title: '登录失败',
          content: String(e),
          showCancel: false,
        });
      });
  },

  scanTable() {
    this.ensureLogin().then((ok) => {
      if (!ok) return;
      wx.scanCode({
        onlyFromCamera: true,
        success: (res) => {
          const result = (res.result || '').trim();
          let tableId = '';
          let qrToken = '';
          if (result.includes('table_id=')) {
            const m = result.match(/table_id=([^&]+)/);
            tableId = m ? decodeURIComponent(m[1]) : '';
            const t = result.match(/qr_token=([^&]+)/);
            qrToken = t ? decodeURIComponent(t[1]) : '';
          } else {
            wx.showToast({ title: '请扫描球台完整二维码', icon: 'none', duration: 2500 });
            return;
          }
          if (!tableId || !qrToken) {
            wx.showToast({ title: '二维码无效，请重新扫描', icon: 'none' });
            return;
          }
          wx.navigateTo({
            url: `/pages/table/table?table_id=${encodeURIComponent(tableId)}&qr_token=${encodeURIComponent(qrToken)}`,
          });
        },
        fail: () => {
          wx.showToast({ title: '扫码已取消', icon: 'none' });
        },
      });
    });
  },

  goRank() {
    wx.switchTab({ url: '/pages/rank/rank' });
  },

  challenge(e) {
    this.ensureLogin().then((ok) => {
      if (!ok) return;
      const target = e.currentTarget.dataset.target;
      wx.showModal({
        title: '发起排位挑战',
        content: `挑战 ${target.nickname}(排名第${target.rank})？需在该桌扫码开始`,
        success: (r) => {
          if (r.confirm) {
            wx.setStorageSync('challenge_target', target);
            this.scanTable();
          }
        },
      });
    });
  },
});
