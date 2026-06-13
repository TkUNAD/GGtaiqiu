const api = require('../../utils/api');
const publicApi = require('../../utils/publicApi');
const { attachLoginHandlers } = require('../../utils/loginHelper');
const { setVenueId } = require('../../utils/venueStore');

const app = getApp();

function parseJoinToken(options) {
  const scene = (options && options.scene) || '';
  const raw = decodeURIComponent(String(scene || options.token || '')).trim();
  if (!raw) return '';
  if (raw.indexOf('vjo_') >= 0) {
    const idx = raw.indexOf('vjo_');
    return raw.slice(idx + 4);
  }
  return raw;
}

Page({
  data: {
    joinToken: '',
    venueName: '',
    venueId: '',
    loadError: '',
    needLogin: false,
    joined: false,
    joining: false,
    logging: false,
    showAuthFallback: false,
    pendingNickname: '',
    pendingAvatar: '',
    agreedToTerms: false,
  },

  onLoad(options) {
    const joinToken = parseJoinToken(options);
    if (!joinToken) {
      this.setData({ loadError: '加入码无效，请重新扫描俱乐部二维码' });
      return;
    }
    this.setData({ joinToken });
    attachLoginHandlers(this, () => this.afterLogin());
    this.loadPreview();
  },

  async loadPreview() {
    try {
      const info = await publicApi.getVenueJoinPreview(this.data.joinToken);
      this.setData({
        venueName: info.venue_name || '',
        venueId: info.venue_id || '',
        loadError: '',
      });
      if (app.globalData.token || wx.getStorageSync('access_token')) {
        this.setData({ needLogin: false });
      } else {
        this.setData({ needLogin: true });
      }
    } catch (e) {
      this.setData({ loadError: String(e) });
    }
  },

  afterLogin() {
    this.setData({ needLogin: false, logging: false });
    this.doJoin();
  },

  async doJoin() {
    if (this.data.joining || this.data.joined) return;
    const token = app.globalData.accessToken || app.globalData.token || wx.getStorageSync('access_token');
    if (!token) {
      this.setData({ needLogin: true });
      return;
    }
    this.setData({ joining: true });
    try {
      const data = await api.joinVenue(this.data.joinToken);
      if (data.venue_id) {
        setVenueId(data.venue_id);
        app.globalData.venueId = data.venue_id;
        if (typeof app.loadVenueStatus === 'function') {
          app.loadVenueStatus();
        }
      }
      this.setData({
        joined: true,
        venueName: data.venue_name || this.data.venueName,
        joining: false,
      });
      wx.showToast({ title: '已加入俱乐部', icon: 'success' });
    } catch (e) {
      this.setData({ joining: false });
      wx.showToast({ title: String(e), icon: 'none' });
    }
  },

  goHome() {
    wx.switchTab({ url: '/pages/index/index' });
  },
});
