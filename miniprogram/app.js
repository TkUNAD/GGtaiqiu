const { getApiBaseUrl, VENUE_ID } = require('./utils/config');
const api = require('./utils/api');

App({
  globalData: {
    baseUrl: '',
    token: '',
    user: null,
    networkOk: false,
    venueId: VENUE_ID,
    venueStatus: null,
    showAds: true,
  },
  onLaunch() {
    this.globalData.baseUrl = getApiBaseUrl();
    console.log('[API] baseUrl =', this.globalData.baseUrl);

    const token = wx.getStorageSync('token');
    const cachedUser = wx.getStorageSync('user');
    if (token) {
      this.globalData.token = token;
      if (cachedUser) {
        this.globalData.user = cachedUser;
      }
      this.refreshProfile();
    }

    this.loadVenueStatus();

    api.ping()
      .then(() => { this.globalData.networkOk = true; })
      .catch((e) => {
        this.globalData.networkOk = false;
        console.warn('[API] ping failed', e);
      });
  },
  loadVenueStatus() {
    const vid = this.globalData.venueId || VENUE_ID;
    api.request(`/api/venue/status?venue_id=${vid}`)
      .then((st) => {
        this.globalData.venueStatus = st;
        this.globalData.showAds = st.show_ads !== false;
      })
      .catch(() => {
        this.globalData.showAds = true;
      });
  },
  refreshProfile() {
    if (!this.globalData.token) return;
    api.request('/api/user/profile')
      .then((profile) => {
        const u = { ...profile.user, tier: profile.tier, rank: profile.rank };
        this.globalData.user = u;
        wx.setStorageSync('user', u);
      })
      .catch((err) => {
        const msg = String(err || '');
        if (msg.indexOf('登录') >= 0 || msg.indexOf('401') >= 0) {
          api.logout();
          this.globalData.user = null;
        }
      });
  },
  setUser(user, token) {
    this.globalData.user = user;
    this.globalData.token = token;
    wx.setStorageSync('user', user);
    wx.setStorageSync('token', token);
  },
});
