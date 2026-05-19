const api = require('../../utils/api');
const app = getApp();

Page({
  data: { summary: null, matchId: '', loadError: '' },

  onLoad(options) {
    this.setData({ matchId: options.match_id || '' });
    this.load();
  },

  async load() {
    if (!this.data.matchId) {
      this.setData({ loadError: '缺少对局编号' });
      return;
    }
    try {
      const summary = await api.request(`/api/match/${this.data.matchId}/summary`);
      this.setData({ summary, loadError: '' });
      if (app.globalData.token) {
        api.request('/api/user/profile').then((profile) => {
          const u = { ...profile.user, tier: profile.tier, rank: profile.rank };
          app.setUser(u, app.globalData.token);
        }).catch(() => {});
      }
    } catch (e) {
      this.setData({ loadError: String(e) });
      wx.showToast({ title: String(e), icon: 'none' });
    }
  },

  onClose() {
    wx.switchTab({ url: '/pages/profile/profile' });
  },
});
