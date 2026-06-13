const api = require('../../utils/api');
const adminApi = require('../../utils/adminApi');
const { getTierStyle } = require('../../utils/tierIcons');
const { attachLoginHandlers } = require('../../utils/loginHelper');
const { getVenueId } = require('../../utils/venueStore');
const { DEFAULT_AVATAR, buildAvatarDisplay } = require('../../utils/avatar');
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
    consoleEntries: [],
    showConsoleSwitcher: false,
    adminEntering: false,
  },

  onLoad() {
    attachLoginHandlers(this, this.load);
  },

  onShow() {
    this.setData({ user: app.globalData.user });
    if (app.globalData.token) {
      this.load();
    } else {
      this.setData({ profile: null, consoleEntries: [] });
    }
    this.checkAdminEligibility();
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
      const rawAvatar = (profile.user && profile.user.avatar) || (app.globalData.user && app.globalData.user.avatar) || '';
      const nickname = (profile.user && profile.user.nickname) || '球友';
      const av = buildAvatarDisplay(rawAvatar, nickname, '球友');
      const user = {
        ...(profile.user || {}),
        avatar: av.avatar,
        nickname,
      };
      this.setData({
        profile: {
          ...profile,
          user,
          hasAvatar: av.hasAvatar,
          avatarInitial: av.avatarInitial,
          ...tierStyle,
          recent_exchanges: recentExchanges,
        },
        user: app.globalData.user,
      });
      if (app.globalData.user) {
        app.globalData.user = { ...app.globalData.user, ...user };
        wx.setStorageSync('user', app.globalData.user);
      }
      this.checkAdminEligibility();
    } catch (e) {
      wx.showToast({ title: e, icon: 'none' });
    }
  },

  async checkAdminEligibility() {
    if (!app.globalData.token) {
      this.setData({ consoleEntries: [] });
      return;
    }
    try {
      let info = await adminApi.checkEligibility(getVenueId());
      let raw = (info && info.console_entries) || [];
      if (!raw.length) {
        try {
          info = await adminApi.syncBindings(getVenueId());
          raw = (info && info.console_entries) || [];
        } catch (syncErr) {
          console.warn('sync-bindings failed:', syncErr);
        }
      }
      const bound = raw.filter((e) => e.entry_type === 'bound');
      const dual = !!(info && (info.has_dual_console || bound.length >= 2));

      if (bound.length >= 1 && adminApi.hasAdminSession()) {
        const session = adminApi.getAdminSession();
        const preferred = wx.getStorageSync('admin_preferred_id');
        const activeId = (session && session.admin_id) || preferred || '';
        const ok = activeId && bound.some((b) => b.admin_id === activeId);
        if (ok) {
          try {
            await adminApi.ensureAdminSession();
          } catch (e) {
            if (!dual) adminApi.logoutAdmin();
          }
        } else if (!dual) {
          adminApi.logoutAdmin();
        }
      } else if (bound.length === 0 && adminApi.hasAdminSession()) {
        adminApi.logoutAdmin();
      }

      const sessionAfter = adminApi.getAdminSession();
      const activeId = (sessionAfter && sessionAfter.admin_id)
        || wx.getStorageSync('admin_preferred_id')
        || '';
      const entries = raw.map((e) => {
        if (e.entry_type !== 'bound') return e;
        return {
          ...e,
          is_active: !!activeId && e.admin_id === activeId,
        };
      });

      this.setData({
        consoleEntries: entries,
        showConsoleSwitcher: dual,
      });
    } catch (err) {
      // 网络或鉴权失败时不强制清空，避免误隐藏已授权的管理入口
      console.warn('checkAdminEligibility failed:', err);
    }
  },

  async onConsoleEntry(e) {
    const ds = e.currentTarget.dataset || {};
    const entryType = ds.entryType || ds.entry_type;
    const adminId = ds.adminId || ds.admin_id || '';
    if (!entryType || this.data.adminEntering) return;

    if (entryType === 'super_auth') {
      wx.navigateTo({
        url: '/pages/admin-scan/admin-scan?mode=super',
        fail: (err) => wx.showToast({ title: err.errMsg || '打开失败', icon: 'none' }),
      });
      return;
    }

    if (entryType === 'venue_auth') {
      wx.navigateTo({
        url: '/pages/admin-scan/admin-scan?intent=venue_bind',
        fail: (err) => wx.showToast({ title: err.errMsg || '打开失败', icon: 'none' }),
      });
      return;
    }

    if (entryType === 'bound' && adminId) {
      const entry = (this.data.consoleEntries || []).find((x) => x.admin_id === adminId);
      const isSuperTarget = entry ? !!entry.is_super : undefined;
      await this.enterBoundAdmin(adminId, isSuperTarget);
    }
  },

  async enterBoundAdmin(adminId, isSuperTarget) {
    if (!adminId || this.data.adminEntering) return;
    this.setData({ adminEntering: true });
    wx.showLoading({ title: '进入中...', mask: true });
    try {
      const session = await adminApi.switchAdmin(adminId);
      if (isSuperTarget === false && adminApi.isSuperSession(session)) {
        throw new Error('未能切换到俱乐部后台，请先在绑定页完成主管理员绑定');
      }
      if (isSuperTarget === true && !adminApi.isSuperSession(session)) {
        throw new Error('未能切换到总后台');
      }
      wx.hideLoading();
      this.checkAdminEligibility();
      wx.redirectTo({
        url: `/pages/admin-console/admin-console?admin_id=${encodeURIComponent(adminId)}`,
        fail: (err) => wx.showToast({ title: err.errMsg || '打开失败', icon: 'none' }),
      });
    } catch (err) {
      wx.hideLoading();
      wx.showToast({ title: String(err), icon: 'none' });
    } finally {
      this.setData({ adminEntering: false });
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

  onProfileAvatarError() {
    const profile = this.data.profile;
    if (!profile || !profile.user) return;
    if (profile.user.avatar === DEFAULT_AVATAR) return;
    this.setData({
      profile: {
        ...profile,
        hasAvatar: true,
        user: { ...profile.user, avatar: DEFAULT_AVATAR },
      },
    });
  },
});
