const api = require('../../utils/api');
const { withRankIcons } = require('../../utils/rank');

Page({
  data: { list: [], loading: true },

  onShow() {
    this.load();
  },

  load() {
    this.setData({ loading: true });
    api.request('/api/rank/list?limit=50')
      .then((list) => this.setData({ list: withRankIcons(list), loading: false }))
      .catch(e => {
        wx.showToast({ title: e, icon: 'none' });
        this.setData({ loading: false });
      });
  },

  onPullDownRefresh() {
    api.request('/api/rank/list?limit=50')
      .then((list) => this.setData({ list: withRankIcons(list), loading: false }))
      .catch((e) => {
        wx.showToast({ title: e, icon: 'none' });
        this.setData({ loading: false });
      })
      .finally(() => wx.stopPullDownRefresh());
  },
});
