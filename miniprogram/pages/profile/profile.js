const api = require('../../utils/api');
const app = getApp();

Page({
  data: {
    profile: null,
    phone: '',
    editNickname: '',
  },

  onShow() {
    this.load();
  },

  async load() {
    if (!app.globalData.token) {
      this.setData({ profile: null });
      return;
    }
    try {
      const profile = await api.request('/api/user/profile');
      this.setData({
        profile,
        phone: profile.user.phone || '',
        editNickname: profile.user.nickname || '',
      });
      if (app.globalData.user) {
        app.globalData.user = { ...app.globalData.user, ...profile.user };
        wx.setStorageSync('user', app.globalData.user);
      }
    } catch (e) {
      wx.showToast({ title: e, icon: 'none' });
    }
  },

  onPhoneInput(e) {
    this.setData({ phone: e.detail.value });
  },

  onNicknameInput(e) {
    this.setData({ editNickname: e.detail.value });
  },

  saveNickname() {
    const nickname = (this.data.editNickname || '').trim();
    if (!nickname) {
      wx.showToast({ title: '昵称不能为空', icon: 'none' });
      return;
    }
    if (nickname.length > 20) {
      wx.showToast({ title: '昵称最多20个字', icon: 'none' });
      return;
    }
    api.request('/api/user/nickname', 'POST', { nickname })
      .then((data) => {
        const u = data.user || {};
        if (app.globalData.user && app.globalData.token) {
          app.setUser({ ...app.globalData.user, ...u }, app.globalData.token);
        }
        const last = wx.getStorageSync('wx_last_profile') || {};
        wx.setStorageSync('wx_last_profile', {
          nickname,
          avatar: last.avatar || u.avatar || '',
        });
        wx.showToast({ title: '昵称已更新', icon: 'success' });
        return this.load();
      })
      .catch((e) => wx.showToast({ title: String(e), icon: 'none' }));
  },

  bindPhone() {
    const phone = (this.data.phone || '').trim();
    if (!phone) {
      wx.showToast({ title: '请输入手机号', icon: 'none' });
      return;
    }
    if (!/^1\d{10}$/.test(phone)) {
      wx.showToast({ title: '请输入11位有效手机号', icon: 'none' });
      return;
    }
    api.request('/api/user/bind-phone', 'POST', { phone })
      .then(() => {
        wx.showToast({ title: '绑定成功' });
        this.load();
      })
      .catch(e => wx.showToast({ title: e, icon: 'none' }));
  },

  goShop() {
    wx.setStorageSync('shop_tab', 'records');
    wx.switchTab({ url: '/pages/shop/shop' });
  },

  goMatches() {
    wx.navigateTo({ url: '/pages/profile-matches/profile-matches' });
  },

  goScoreLogs() {
    wx.navigateTo({ url: '/pages/profile-logs/profile-logs' });
  },

  openMatch(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) return;
    wx.navigateTo({ url: `/pages/match-result/match-result?match_id=${encodeURIComponent(id)}` });
  },

  goLogin() {
    wx.switchTab({ url: '/pages/index/index' });
  },
});
