const adminApi = require('../../utils/adminApi');
const membershipRenew = require('../../utils/membershipRenew');

const ROLE_ZH = { owner: '主管理员', admin: '子管理员', super: '总管理员' };

Page({
  data: {
    session: null,
    menu: [],
    badges: null,
    roleLabel: '',
    consoleTitle: '',
    consoleSubtitle: '',
    isVenueConsole: false,
    loading: true,
    membershipActive: true,
    membershipExpires: '',
    membershipPlans: [],
  },

  onLoad(options) {
    this._expectedAdminId = (options && options.admin_id) || '';
  },

  onShow() {
    this._expectedAdminId = this._expectedAdminId
      || wx.getStorageSync('admin_preferred_id')
      || '';
    this.load();
  },

  async load() {
    this.setData({ loading: true });
    const expectedId = this._expectedAdminId
      || wx.getStorageSync('admin_preferred_id')
      || '';
    try {
      if (expectedId) {
        await adminApi.switchAdmin(expectedId);
      }
      await adminApi.ensureAdminSession(expectedId);
      let data = await adminApi.fetchMenu();
      let session = data.session || adminApi.getAdminSession();
      if (expectedId && session && session.admin_id !== expectedId) {
        await adminApi.switchAdmin(expectedId);
        data = await adminApi.fetchMenu();
        session = data.session || adminApi.getAdminSession();
      }
      const isSuper = adminApi.isSuperSession(session);
      const isVenue = !isSuper && (data.console_type || session.console_type) === 'venue';
      const badges = data.badges || {};
      const menu = (data.menu || []).map((item) => {
        let badge = 0;
        if (item.badge_key === 'pending_all') badge = badges.pending_all || 0;
        return { ...item, badge };
      });
      wx.setNavigationBarTitle({
        title: isVenue ? '俱乐部后台' : '总后台',
      });
      const patch = {
        session,
        menu,
        badges,
        isVenueConsole: isVenue,
        consoleTitle: isVenue ? (session.venue_name || '俱乐部后台') : '台球天梯 · 总后台',
        consoleSubtitle: isVenue ? '俱乐部管理端' : '平台运营管理',
        roleLabel: ROLE_ZH[session.admin_role] || session.admin_role || '',
        loading: false,
      };
      if (isVenue) {
        try {
          const mem = await membershipRenew.fetchMembershipSummary();
          patch.membershipActive = !!mem.is_member_active;
          patch.membershipExpires = mem.member_expires_date || (mem.member_expires_at || '').slice(0, 10);
          patch.membershipPlans = mem.plans || [];
        } catch (e) {
          patch.membershipActive = !!session.is_member_active;
          patch.membershipExpires = '';
          patch.membershipPlans = [];
        }
      }
      this.setData(patch);
    } catch (e) {
      this.setData({ loading: false });
      const wasSuper = adminApi.isSuperSession(adminApi.getAdminSession());
      adminApi.logoutAdmin();
      const msg = String(e);
      wx.showModal({
        title: '管理登录失效',
        content: msg.indexOf('绑定') >= 0 ? msg : (msg + '\n\n请使用总后台账号密码重新登录'),
        showCancel: false,
        success: () => {
          const url = wasSuper
            ? '/pages/admin-scan/admin-scan?mode=super&fail=1'
            : '/pages/admin-scan/admin-scan?fail=1';
          wx.redirectTo({ url });
        },
      });
    }
  },

  async loadMembership() {
    if (!this.data.isVenueConsole) return;
    try {
      const mem = await membershipRenew.fetchMembershipSummary();
      this.setData({
        membershipActive: !!mem.is_member_active,
        membershipExpires: mem.member_expires_date || (mem.member_expires_at || '').slice(0, 10),
        membershipPlans: mem.plans || [],
      });
    } catch (e) {
      /* ignore */
    }
  },

  onRenewMembership() {
    membershipRenew.openRenewPicker(this.data.membershipPlans, () => {
      this.load();
    });
  },

  openModule(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) return;
    if (e.currentTarget.dataset.disabled === '1') {
      wx.showToast({ title: '会员已到期，请续费后使用', icon: 'none' });
      return;
    }
    wx.navigateTo({ url: `/pages/admin-module/admin-module?m=${encodeURIComponent(id)}` });
  },

  onLogout() {
    adminApi.logoutAdmin();
    wx.showToast({ title: '已退出管理', icon: 'none' });
    wx.switchTab({ url: '/pages/profile/profile' });
  },
});
