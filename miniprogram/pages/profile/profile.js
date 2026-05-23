const api = require('../../utils/api');
const { getTierStyle } = require('../../utils/tierIcons');
const { attachLoginHandlers } = require('../../utils/loginHelper');
const app = getApp();

const EXCHANGE_STATUS = {
  pending: '待审核',
  approved: '已通过',
  rejected: '已拒绝',
};

Page({
  data: {
    profile: null,
    user: null,
    logging: false,
    showAuthFallback: false,
    pendingNickname: '',
    pendingAvatar: '',
    agreedToTerms: false,
  },

  onLoad() {
    attachLoginHandlers(this, this.load);
  },

  onShow() {
    this.setData({ user: app.globalData.user });
    if (app.globalData.token) {
      this.load();
    } else {
      this.setData({ profile: null });
    }
  },

  async load() {
    if (!app.globalData.token) {
      this.setData({ profile: null });
      return;
    }
    try {
      const profile = await api.request('/api/user/profile');
      const recentExchanges = (profile.recent_exchanges || []).map((item) => ({
        ...item,
        status: EXCHANGE_STATUS[item.status] || item.status,
      }));
      const tierStyle = getTierStyle(profile.tier && profile.tier.tier_index);
      this.setData({
        profile: {
          ...profile,
          ...tierStyle,
          recent_exchanges: recentExchanges,
        },
        user: app.globalData.user,
      });
      if (app.globalData.user) {
        app.globalData.user = { ...app.globalData.user, ...profile.user };
        wx.setStorageSync('user', app.globalData.user);
      }
    } catch (e) {
      wx.showToast({ title: e, icon: 'none' });
    }
  },

  goShop() {
    wx.switchTab({ url: '/pages/shop/shop' });
  },

  goMatches() {
    wx.navigateTo({ url: '/pages/profile-matches/profile-matches' });
  },

  goScoreLogs() {
    wx.navigateTo({ url: '/pages/profile-logs/profile-logs' });
  },

  goExchanges() {
    wx.navigateTo({ url: '/pages/profile-exchanges/profile-exchanges' });
  },

  openMatch(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) return;
    wx.navigateTo({ url: `/pages/match-result/match-result?match_id=${encodeURIComponent(id)}` });
  },
});
