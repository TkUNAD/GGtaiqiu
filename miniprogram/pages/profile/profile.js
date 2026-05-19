const api = require('../../utils/api');
const app = getApp();

Page({
  data: {
    profile: null,
    phone: '',
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
      });
    } catch (e) {
      wx.showToast({ title: e, icon: 'none' });
    }
  },

  onPhoneInput(e) {
    this.setData({ phone: e.detail.value });
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

  goLogin() {
    wx.switchTab({ url: '/pages/index/index' });
  },
});
