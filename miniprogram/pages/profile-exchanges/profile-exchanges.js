const api = require('../../utils/api');

const STATUS = { pending: '待审核', approved: '已通过', rejected: '已拒绝' };

Page({
  data: { list: [], loading: true, loadError: '' },

  onLoad() {
    this.load();
  },

  async load() {
    this.setData({ loading: true, loadError: '' });
    try {
      const list = await api.request('/api/user/exchanges?limit=50');
      this.setData({
        list: (list || []).map((item) => ({
          ...item,
          statusLabel: STATUS[item.status] || item.status,
        })),
        loading: false,
      });
    } catch (e) {
      this.setData({ loadError: String(e), loading: false, list: [] });
    }
  },
});
