const adminApi = require('../../utils/adminApi');
const app = getApp();

Page({
  data: {
    scanning: false,
    showSuperForm: false,
    showVenueBind: false,
    showVenueSection: false,
    showScanEntry: false,
    superUser: '',
    superPass: '',
    superLogging: false,
    venueUser: '',
    venuePass: '',
  },

  /** 总后台一次性初始化码 → super-setup（勿走管理登录扫码） */
  routeScene(raw) {
    const s = decodeURIComponent(String(raw || '')).trim();
    if (!adminApi.isSuperSetupScene(s)) return false;
    let token = s;
    if (token.indexOf('sas_') >= 0) {
      token = token.slice(token.indexOf('sas_') + 4);
    }
    wx.redirectTo({
      url: `/pages/super-setup/super-setup?scene=${encodeURIComponent(token)}`,
    });
    return true;
  },

  onLoad(options) {
    const scene = (options && (options.scene || options.token)) || '';
    this._intent = (options && options.intent) || '';
    if (options && options.mode === 'super') {
      this.setData({ showSuperForm: true });
    }
    if (
      options
      && (options.fail === '1'
        || options.fail === 'true'
        || options.intent === 'venue_bind'
        || options.no_auto === '1')
    ) {
      this._skipAutoRelogin = true;
    }
    if (this._intent === 'venue_bind') {
      this.setData({ showVenueBind: true, showVenueSection: true });
    }
    if (scene && this.routeScene(scene)) return;
    if (scene) {
      this.handleToken(decodeURIComponent(scene));
    }
  },

  async refreshVisibility() {
    try {
      const info = await adminApi.checkEligibility();
      const showSuper = !!(
        info && (info.show_super_login_entry || (info.eligible && info.is_super))
      );
      const showVenue = !!(info && (info.show_login_entry || info.show_owner_bind_entry));
      this.setData({
        showSuperForm: showSuper || this.data.showSuperForm,
        showVenueSection: showVenue,
        showScanEntry: showSuper || showVenue || !!(info && info.eligible),
      });
    } catch (e) {
      /* ignore */
    }
  },

  async onShow() {
    if (!app.globalData.token && !wx.getStorageSync('access_token')) {
      wx.showModal({
        title: '请先登录',
        content: '请先在「我的」完成微信授权登录',
        showCancel: false,
        success: () => wx.switchTab({ url: '/pages/profile/profile' }),
      });
      return;
    }
    if (!this._skipAutoRelogin && await this.tryRelogin()) return;
    await this.refreshVisibility();
  },

  async tryRelogin() {
    if (this._intent === 'venue_bind' || this._skipAutoRelogin) {
      return false;
    }
    try {
      const info = await adminApi.checkEligibility();
      if (!(info && info.eligible)) {
        if (adminApi.hasAdminSession()) adminApi.logoutAdmin();
        return false;
      }
      if (info.has_multiple_consoles && !wx.getStorageSync('admin_preferred_id')) {
        return false;
      }
      const preferred = wx.getStorageSync('admin_preferred_id') || '';
      const bound = (info.admin_identities || []).filter((x) => x.admin_id);
      if (preferred && bound.length > 1) {
        await adminApi.switchAdmin(preferred);
      } else {
        await adminApi.ensureAdminSession(preferred);
      }
      const q = preferred ? `?admin_id=${encodeURIComponent(preferred)}` : '';
      wx.redirectTo({ url: `/pages/admin-console/admin-console${q}` });
      return true;
    } catch (e) {
      adminApi.logoutAdmin();
      return false;
    }
  },

  onScan() {
    if (this.data.scanning) return;
    this.setData({ scanning: true });
    wx.scanCode({
      onlyFromCamera: false,
      success: (res) => {
        const raw = res.result || '';
        if (this.routeScene(raw)) return;
        const token = adminApi.parseQrToken(raw);
        if (!token) {
          const isSetup = adminApi.isSuperSetupScene(raw);
          wx.showToast({
            title: isSetup ? '正在打开总后台初始化…' : '无效的管理二维码',
            icon: 'none',
          });
          if (isSetup) this.routeScene(raw);
          return;
        }
        this.handleToken(token);
      },
      fail: () => wx.showToast({ title: '扫码取消', icon: 'none' }),
      complete: () => this.setData({ scanning: false }),
    });
  },

  async handleToken(token) {
    wx.showLoading({ title: '验证中...', mask: true });
    try {
      const result = await adminApi.scanLogin(token);
      wx.hideLoading();
      if (result && result.registered) {
        wx.showModal({
          title: '授权成功',
          content: result.message || '请在「我的」使用总后台登录',
          showCancel: false,
          success: () => {
            this.refreshVisibility();
            wx.switchTab({ url: '/pages/profile/profile' });
          },
        });
        return;
      }
      wx.showToast({ title: '登录成功', icon: 'success' });
      setTimeout(() => wx.redirectTo({ url: '/pages/admin-console/admin-console' }), 400);
    } catch (e) {
      wx.hideLoading();
      wx.showModal({ title: '失败', content: String(e), showCancel: false });
    }
  },

  toggleVenueBind() {
    this.setData({ showVenueBind: !this.data.showVenueBind });
  },

  onSuperUser(e) {
    this.setData({ superUser: e.detail.value });
  },

  onSuperPass(e) {
    this.setData({ superPass: e.detail.value });
  },

  onVenueUser(e) {
    this.setData({ venueUser: e.detail.value });
  },

  onVenuePass(e) {
    this.setData({ venuePass: e.detail.value });
  },

  async onSuperLogin() {
    const { superUser, superPass } = this.data;
    if (!superUser || !superPass) {
      wx.showToast({ title: '请输入总后台账号密码', icon: 'none' });
      return;
    }
    this.setData({ superLogging: true });
    wx.showLoading({ title: '登录中...', mask: true });
    try {
      await adminApi.superLogin(superUser.trim(), superPass);
      wx.hideLoading();
      wx.showToast({ title: '登录成功', icon: 'success' });
      setTimeout(() => {
        wx.redirectTo({ url: '/pages/admin-console/admin-console' });
      }, 400);
    } catch (e) {
      wx.hideLoading();
      wx.showModal({ title: '登录失败', content: String(e), showCancel: false });
    } finally {
      this.setData({ superLogging: false });
    }
  },

  async onVenueBind() {
    const { venueUser, venuePass } = this.data;
    if (!venueUser || !venuePass) {
      wx.showToast({ title: '请输入俱乐部账号密码', icon: 'none' });
      return;
    }
    wx.showLoading({ title: '绑定中...', mask: true });
    try {
      const session = await adminApi.bindOwner(venueUser.trim(), venuePass);
      wx.hideLoading();
      wx.showToast({ title: '绑定成功', icon: 'success' });
      const aid = (session && session.admin_id) || wx.getStorageSync('admin_preferred_id') || '';
      setTimeout(() => {
        const q = aid ? `?admin_id=${encodeURIComponent(aid)}` : '';
        wx.redirectTo({ url: `/pages/admin-console/admin-console${q}` });
      }, 400);
    } catch (e) {
      wx.hideLoading();
      wx.showModal({ title: '绑定失败', content: String(e), showCancel: false });
    }
  },
});
