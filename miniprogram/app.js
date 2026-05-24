const { getApiBaseUrl, VENUE_ID } = require('./utils/config');
const { getVenueId } = require('./utils/venueStore');
const api = require('./utils/api');

App({
  globalData: {
    baseUrl: '',
    token: '',
    accessToken: '',
    refreshToken: '',
    user: null,
    networkOk: false,
    venueId: getVenueId(),
    venueStatus: null,
    showAds: true,
    location: null,
    version: '2.0.1',
  },
  onLaunch() {
    this.globalData.baseUrl = getApiBaseUrl();
    console.log('[API] baseUrl =', this.globalData.baseUrl);

    const access = wx.getStorageSync('access_token') || wx.getStorageSync('token');
    const refresh = wx.getStorageSync('refresh_token');
    const cachedUser = wx.getStorageSync('user');
    if (access || refresh) {
      this.globalData.accessToken = access;
      this.globalData.token = access;
      this.globalData.refreshToken = refresh;
      if (cachedUser) this.globalData.user = cachedUser;
      if (access) {
        this.refreshProfile();
      } else if (refresh) {
        api.tryRefreshToken().then(() => this.refreshProfile()).catch(() => {});
      }
    }

    this.loadVenueStatus();
    this.initLocation();

    api.ping()
      .then(() => { this.globalData.networkOk = true; })
      .catch((e) => {
        this.globalData.networkOk = false;
        console.warn('[API] ping failed', e);
      });
  },
  initLocation() {
    const { ensureLocation } = require('./utils/locationHelper');
    ensureLocation(this).catch(() => {});
  },
  ensureLocation() {
    const { ensureLocation } = require('./utils/locationHelper');
    return ensureLocation(this);
  },
  loadVenueStatus() {
    const vid = getVenueId();
    this.globalData.venueId = vid;
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
    if (!this.globalData.accessToken && !this.globalData.token) return;
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
  setUser(user, accessToken, refreshToken) {
    this.globalData.user = user;
    this.globalData.accessToken = accessToken || '';
    this.globalData.token = accessToken || '';
    if (refreshToken) this.globalData.refreshToken = refreshToken;
    wx.setStorageSync('user', user);
    wx.setStorageSync('access_token', accessToken || '');
    wx.setStorageSync('token', accessToken || '');
    if (refreshToken) wx.setStorageSync('refresh_token', refreshToken);
  },
});
