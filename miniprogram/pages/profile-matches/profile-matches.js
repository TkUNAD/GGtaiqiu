const api = require('../../utils/api');

Page({
  data: {
    list: [],
    loading: true,
    loadError: '',
  },

  onLoad() {
    this.load();
  },

  async load() {
    this.setData({ loading: true, loadError: '' });
    try {
      const list = await api.request('/api/user/matches?limit=20');
      this.setData({ list: list || [], loading: false });
    } catch (e) {
      this.setData({ loadError: String(e), loading: false, list: [] });
    }
  },

  openMatch(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) return;
    wx.navigateTo({ url: `/pages/match-result/match-result?match_id=${encodeURIComponent(id)}` });
  },
});
