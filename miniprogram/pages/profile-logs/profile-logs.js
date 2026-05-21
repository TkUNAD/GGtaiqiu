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
      const list = await api.request('/api/user/score-logs?limit=20');
      this.setData({ list: list || [], loading: false });
    } catch (e) {
      this.setData({ loadError: String(e), loading: false, list: [] });
    }
  },
});
