const api = require('../../utils/api');
const { VENUE_ID } = require('../../utils/config');
const { decorateList } = require('../../utils/rank');
const { getTierStyle } = require('../../utils/tierIcons');

Page({
  data: {
    tab: 'club',
    list: [],
    loading: true,
    playerDetail: null,
  },

  onShow() {
    this.load();
  },

  switchTab(e) {
    const tab = e.currentTarget.dataset.tab;
    if (tab === this.data.tab) return;
    this.setData({ tab });
    this.load();
  },

  load() {
    this.setData({ loading: true });
    const url = this.data.tab === 'club'
      ? `/api/rank/club?limit=50&venue_id=${VENUE_ID}`
      : '/api/rank/global?limit=50';
    api.request(url)
      .then((list) => this.setData({ list: decorateList(list), loading: false }))
      .catch((e) => {
        wx.showToast({ title: e, icon: 'none' });
        this.setData({ loading: false });
      });
  },

  onPullDownRefresh() {
    this.load();
    wx.stopPullDownRefresh();
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
});
