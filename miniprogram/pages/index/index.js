const api = require('../../utils/api');
const { getApiBaseUrl, SHOW_TEST_LOGIN } = require('../../utils/config');
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
    showTestLogin: SHOW_TEST_LOGIN,
  },

  onShow() {
    const app = getApp();
    this.setData({
      user: app.globalData.user,
      apiUrl: app.globalData.baseUrl || getApiBaseUrl(),
    });
    this.loadData();
  },

  async retryNetwork() {
    const app = getApp();
    app.globalData.baseUrl = getApiBaseUrl();
    this.setData({ apiUrl: app.globalData.baseUrl, netError: '' });
    await this.loadData();
  },

  async ensureLogin() {
    if (!getApp().globalData.token) {
      wx.showToast({ title: '请先点击下方「微信授权登录」', icon: 'none', duration: 2500 });
      return false;
    }
    return true;
  },

  async loadData() {
    try {
      await api.ping();
      this.setData({ netError: '' });
    } catch (e) {
      const msg = typeof e === 'string' ? e : '网络连接失败';
      this.setData({ netError: msg });
      return;
    }
    try {
      const topRank = withRankIcons(await api.request('/api/rank/list?limit=5'));
      const { VENUE_ID } = require('../../utils/config');
      const tables = await api.request('/api/tables' + (VENUE_ID ? `?venue_id=${VENUE_ID}` : ''));
      this.setData({ topRank, tables });
    } catch (e) {
      console.error('[loadData] rank/tables', e);
      wx.showToast({ title: '排行或桌台加载失败', icon: 'none' });
    }
    const app = getApp();
    if (app.globalData.token) {
      try {
        const ch = await api.request('/api/rank/challenge-targets');
        this.setData({ challengeTargets: ch.targets || [] });
      } catch (e) {
        console.error('[loadData] challenge', e);
        wx.showToast({ title: '挑战列表加载失败', icon: 'none' });
      }
    }
  },

  async loginTest(e) {
    const role = e.currentTarget.dataset.role;
    const map = {
      a: { code: 'test_player_a', nickname: '选手A' },
      b: { code: 'test_player_b', nickname: '选手B' },
    };
    const item = map[role];
    if (!item || this.data.logging) return;
    this.setData({ logging: true });
    try {
      await api.loginAsTest(item.code, item.nickname);
      const app = getApp();
      this.setData({ user: app.globalData.user, netError: '', logging: false });
      wx.showToast({ title: item.nickname + ' 登录成功', icon: 'success' });
      this.loadData();
    } catch (err) {
      this.setData({ logging: false });
      wx.showModal({ title: '登录失败', content: String(err), showCancel: false });
    }
  },

  onLogout() {
    api.logout();
    this.setData({ user: null, challengeTargets: [] });
    wx.showToast({ title: '已退出', icon: 'none' });
  },

  async onLogin() {
    if (this.data.logging) return;
    this.setData({ logging: true });
    try {
      await api.login();
      const app = getApp();
      this.setData({
        user: app.globalData.user,
        netError: '',
        logging: false,
      });
      wx.showToast({ title: '登录成功', icon: 'success' });
      this.loadData();
    } catch (e) {
      this.setData({ logging: false });
      const msg = typeof e === 'string' ? e : '登录失败';
      wx.showModal({
        title: '登录失败',
        content: msg + '\n\n请确认后端已启动，且网络设置正确。',
        showCancel: false,
      });
    }
  },

  async scanTable() {
    if (!(await this.ensureLogin())) return;
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
  },

  goRank() {
    wx.switchTab({ url: '/pages/rank/rank' });
  },

  async challenge(e) {
    if (!(await this.ensureLogin())) return;
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
  },
});
