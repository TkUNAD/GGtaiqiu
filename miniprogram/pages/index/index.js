const api = require('../../utils/api');
const { getApiBaseUrl, VENUE_ID } = require('../../utils/config');
const { decorateList } = require('../../utils/rank');
const { getTierStyle } = require('../../utils/tierIcons');
const app = getApp();

Page({
  data: {
    loggedIn: false,
    topRank: [],
    tables: [],
    challengeTargets: [],
    challengeHint: '',
    todayScore: 0,
    rankedRemainingDaily: 0,
    netError: '',
    apiUrl: '',
    playerDetail: null,
  },

  onShow() {
    const loggedIn = !!app.globalData.token;
    this.setData({
      loggedIn,
      apiUrl: app.globalData.baseUrl || getApiBaseUrl(),
    });
    this.loadData();
  },

  retryNetwork() {
    app.globalData.baseUrl = getApiBaseUrl();
    this.setData({ apiUrl: app.globalData.baseUrl, netError: '' });
    this.loadData();
  },

  goProfile() {
    wx.switchTab({ url: '/pages/profile/profile' });
  },

  loadData() {
    const self = this;
    const reqId = (this._loadSeq || 0) + 1;
    this._loadSeq = reqId;
    const venueQ = VENUE_ID ? `?venue_id=${VENUE_ID}` : '';
    return api.ping()
      .then(() => {
        if (self._loadSeq !== reqId) return null;
        self.setData({ netError: '' });
        return api.request(`/api/home/summary${venueQ}`);
      })
      .then((data) => {
        if (!data || self._loadSeq !== reqId) return;
        const topRank = decorateList(data.top_rank || []);
        const targets = decorateList(data.challenge_targets || []);
        let challengeHint = '';
        if (self.data.loggedIn && !targets.length) {
          challengeHint = data.my_rank >= 9999
            ? '您暂无天梯排名，暂无可挑战玩家'
            : '当前没有符合规则的可挑战玩家';
        }
        self.setData({
          topRank,
          tables: data.tables || [],
          challengeTargets: targets,
          challengeHint,
          todayScore: data.today_score || 0,
          rankedRemainingDaily: data.ranked_remaining_daily ?? 0,
        });
      })
      .catch((e) => {
        const msg = typeof e === 'string' ? e : '网络连接失败';
        self.setData({ netError: msg });
      });
  },

  ensureLogin() {
    if (!app.globalData.token) {
      wx.showToast({ title: '请先在「我的」完成微信授权登录', icon: 'none', duration: 2500 });
      return Promise.resolve(false);
    }
    return Promise.resolve(true);
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
          wx.removeStorageSync('challenge_target');
          wx.showToast({ title: '扫码已取消', icon: 'none' });
        },
      });
    });
  },

  goRank() {
    wx.switchTab({ url: '/pages/rank/rank' });
  },

  showPlayer(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) return;
    api.request(`/api/rank/player/${id}`)
      .then((p) => {
        this.setData({
          playerDetail: { ...p, ...getTierStyle(p.tier_index) },
        });
      })
      .catch((err) => wx.showToast({ title: err, icon: 'none' }));
  },

  closePlayer() {
    this.setData({ playerDetail: null });
  },

  noop() {},

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
