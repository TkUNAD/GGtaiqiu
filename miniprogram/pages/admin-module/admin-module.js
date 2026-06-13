const adminApi = require('../../utils/adminApi');
const ladderForm = require('../../utils/ladderForm');
const membershipRenew = require('../../utils/membershipRenew');

const MODULE_TITLES = {
  dashboard: '仪表盘',
  review: '审核中心',
  matches: '对局管理',
  users: '玩家管理',
  tables: '桌台管理',
  ladder: '天梯规则',
  venues: '球房会员',
  products: '兑换商品',
  exchanges: '兑换记录',
  logs: '积分明细',
  staff: '管理员设置',
  venue_location: '球房位置',
  mp_wechat: '授权微信',
  settings: '系统设置',
};

/** 总后台可访问模块（与 Web 总后台能力对齐，无球房会员以外的俱乐部项） */
const SUPER_MODULES = new Set([
  'dashboard', 'ladder', 'venues', 'mp_wechat', 'settings',
]);
/** 俱乐部后台可访问模块（与 Web venue-only-nav 一致，含 staff） */
const VENUE_MODULES = new Set([
  'dashboard', 'venue_location', 'matches', 'users', 'tables', 'review', 'ladder',
  'products', 'exchanges', 'logs', 'staff',
]);

const STATUS_ZH = {
  pending_review: '待审核',
  pending: '待审核',
  playing: '进行中',
  finished: '已结束',
};

Page({
  data: {
    module: '',
    session: null,
    isSuperConsole: false,
    loading: true,
    canWrite: false,
    canReview: true,
    canTable: false,
    canLadder: false,
    reviewTab: 'match',
    reviewLogList: [],
    pendingMatches: [],
    pendingExchanges: [],
    reviewedOps: {},
    matchList: [],
    userList: [],
    tableList: [],
    productList: [],
    exchangeList: [],
    logList: [],
    venueList: [],
    staffList: [],
    playerPickList: [],
    dashItems: [],
    venueRows: [],
    ladderSections: [],
    ladderRules: {},
    ladderTip: '',
    ladderDesc: '',
    ladderHasCustom: false,
    ladderIsGlobal: false,
    inviteQr: '',
    venueTab: 'list',
    venueAppList: [],
    deletedVenueList: [],
    venueDetailVisible: false,
    venueDetail: null,
    mpAllowList: [],
    mpAllowQr: '',
    canPromotePlayers: false,
    membershipActive: true,
    membershipExpires: '',
    membershipPlans: [],
    disabledModuleIds: [],
    venueLocationAddress: '',
    venueLocationLat: '',
    venueLocationLng: '',
    venueLocationHas: false,
    venueLocationSummary: '',
  },

  onLoad(options) {
    const m = (options && options.m) || 'dashboard';
    this.setData({ module: m });
  },

  onShow() {
    this.initAndLoad();
  },

  async initAndLoad() {
    if (!adminApi.hasAdminSession()) {
      wx.redirectTo({ url: '/pages/admin-scan/admin-scan' });
      return;
    }
    const preferredId = wx.getStorageSync('admin_preferred_id') || '';
    let session = adminApi.getAdminSession();
    let menuIds = [];
    let disabledModuleIds = [];
    try {
      await adminApi.ensureAdminSession(preferredId);
      const menuData = await adminApi.fetchMenu();
      session = menuData.session || session;
      const menuList = menuData.menu || [];
      menuIds = menuList.map((x) => x.id);
      disabledModuleIds = menuList.filter((x) => x.disabled).map((x) => x.id);
      if (disabledModuleIds.indexOf(this.data.module) >= 0) {
        wx.showToast({ title: '会员已到期，请续费后使用', icon: 'none' });
        setTimeout(() => wx.navigateBack(), 1200);
        return;
      }
      if (menuIds.length && menuIds.indexOf(this.data.module) < 0) {
        wx.showToast({ title: '当前后台无此功能', icon: 'none' });
        setTimeout(() => wx.navigateBack(), 1200);
        return;
      }
    } catch (e) {
      wx.redirectTo({ url: '/pages/admin-scan/admin-scan' });
      return;
    }
    const isSuper = adminApi.isSuperSession(session);
    const allowed = isSuper ? SUPER_MODULES : VENUE_MODULES;
    if (!allowed.has(this.data.module)) {
      wx.showToast({ title: isSuper ? '总后台无此功能' : '俱乐部后台无此功能', icon: 'none' });
      setTimeout(() => wx.navigateBack(), 1200);
      return;
    }
    const prefix = isSuper ? '总后台 · ' : '俱乐部 · ';
    wx.setNavigationBarTitle({
      title: prefix + (MODULE_TITLES[this.data.module] || '管理功能'),
    });
    const canWrite = adminApi.canWrite(session);
    const expired = !isSuper && !session.is_member_active;
    this.setData({
      session,
      isSuperConsole: isSuper,
      canWrite,
      canReview: isSuper || (!expired),
      canTable: isSuper || adminApi.hasPerm(session, 'table_manage'),
      canLadder: isSuper || adminApi.hasPerm(session, 'ladder_settings'),
      canPromotePlayers: !isSuper && !!(session && session.can_promote_players),
      disabledModuleIds,
      loading: true,
    });
    await this.loadModule();
  },

  async loadModule() {
    const { module } = this.data;
    try {
      if (module === 'dashboard') await this.loadDashboard();
      else if (module === 'venue_location') await this.loadVenueLocation();
      else if (module === 'review') await this.loadReview();
      else if (module === 'matches') await this.loadMatches();
      else if (module === 'users') await this.loadUsers();
      else if (module === 'tables') await this.loadTables();
      else if (module === 'ladder') await this.loadLadder();
      else if (module === 'venues') {
        if (!adminApi.isSuperSession(this.data.session)) {
          wx.showToast({ title: '俱乐部后台无球房会员功能', icon: 'none' });
          setTimeout(() => wx.navigateBack(), 800);
          return;
        }
        await this.loadVenues();
      }
      else if (module === 'products') await this.loadProducts();
      else if (module === 'exchanges') await this.loadExchanges();
      else if (module === 'logs') await this.loadLogs();
      else if (module === 'staff') await this.loadStaff();
      else if (module === 'mp_wechat') await this.loadMpWechatAllowlist();
      else if (module === 'settings') await this.loadSettings();
      this.setData({ loading: false });
    } catch (e) {
      this.setData({ loading: false });
      wx.showToast({ title: String(e), icon: 'none' });
    }
  },

  async loadDashboard() {
    const d = await adminApi.adminRequest('/api/admin/dashboard');
    const isSuper = adminApi.isSuperSession(this.data.session);
    if (isSuper) {
      const items = [
        { key: 'v', label: '球房数', val: d.venues_count || 0 },
        { key: 'a', label: '有效会员球房', val: d.active_venues_count || 0 },
        { key: 't', label: '桌台总数', val: d.total_tables || 0 },
        { key: 'm', label: '关联玩家', val: d.total_member_count || 0 },
        { key: 'pm', label: '对局待审', val: d.pending_matches || 0 },
        { key: 'pe', label: '兑换待审', val: d.pending_exchanges || 0 },
      ];
      this.setData({ dashItems: items, venueRows: d.venues || [] });
    } else {
      const items = [
        { key: 'u', label: '注册玩家', val: d.users_count || 0 },
        { key: 'g', label: '总对局', val: d.matches_count || 0 },
        { key: 'pm', label: '对局待审', val: d.pending_matches || 0 },
        { key: 'pb', label: '炸清待审', val: d.pending_bonus_reviews || 0 },
        { key: 'pe', label: '兑换待审', val: d.pending_exchanges || 0 },
      ];
      this.setData({
        dashItems: items,
        venueRows: [],
        membershipActive: !!d.is_member_active,
        membershipExpires: d.member_expires_date || (d.member_expires_at || '').slice(0, 10),
        membershipPlans: d.membership_plans || [],
      });
    }
  },

  openRenewPicker() {
    membershipRenew.openRenewPicker(this.data.membershipPlans, () => {
      this.loadDashboard();
    });
  },

  async loadVenueLocation() {
    try {
      const d = await adminApi.adminRequest('/api/admin/venue/location');
      const has = !!d.has_location;
      this.setData({
        venueLocationAddress: d.address || '',
        venueLocationLat: d.latitude != null ? String(d.latitude) : '',
        venueLocationLng: d.longitude != null ? String(d.longitude) : '',
        venueLocationHas: has,
        venueLocationSummary: has
          ? `${d.address || '未填地址'} · ${Number(d.latitude).toFixed(6)}, ${Number(d.longitude).toFixed(6)}`
          : '尚未设置坐标，顾客小程序将无法显示距离',
      });
    } catch (e) {
      this.setData({
        venueLocationHas: false,
        venueLocationSummary: String(e).indexOf('404') >= 0
          ? '后端尚未更新，请重新部署后再设置'
          : `加载失败：${String(e)}`,
      });
    }
  },

  chooseVenueLocationOnMap() {
    const lat = parseFloat(this.data.venueLocationLat);
    const lng = parseFloat(this.data.venueLocationLng);
    const opts = {};
    if (isFinite(lat) && isFinite(lng)) {
      opts.latitude = lat;
      opts.longitude = lng;
    }
    wx.chooseLocation({
      ...opts,
      success: (res) => {
        const addr = [res.name, res.address].filter(Boolean).join(' · ') || res.address || '';
        this.setData({
          venueLocationAddress: addr,
          venueLocationLat: Number(res.latitude).toFixed(6),
          venueLocationLng: Number(res.longitude).toFixed(6),
        });
      },
      fail: (err) => {
        const msg = (err && err.errMsg) || '';
        if (msg.indexOf('cancel') >= 0) return;
        wx.showToast({ title: msg || '选点失败', icon: 'none' });
      },
    });
  },

  onVenueAddressInput(e) {
    this.setData({ venueLocationAddress: (e.detail && e.detail.value) || '' });
  },

  onVenueLatInput(e) {
    this.setData({ venueLocationLat: (e.detail && e.detail.value) || '' });
  },

  onVenueLngInput(e) {
    this.setData({ venueLocationLng: (e.detail && e.detail.value) || '' });
  },

  async saveVenueLocation() {
    const latRaw = (this.data.venueLocationLat || '').trim();
    const lngRaw = (this.data.venueLocationLng || '').trim();
    if (!latRaw || !lngRaw) {
      wx.showToast({ title: '请先在地图上选点', icon: 'none' });
      return;
    }
    const lat = parseFloat(latRaw);
    const lng = parseFloat(lngRaw);
    if (!isFinite(lat) || !isFinite(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      wx.showToast({ title: '坐标无效，请重新选点', icon: 'none' });
      return;
    }
    wx.showLoading({ title: '保存中...', mask: true });
    try {
      await adminApi.adminRequest('/api/admin/venue/location', 'PUT', {
        address: (this.data.venueLocationAddress || '').trim(),
        latitude: Number(lat.toFixed(6)),
        longitude: Number(lng.toFixed(6)),
      });
      wx.hideLoading();
      wx.showToast({ title: '已保存', icon: 'success' });
      await this.loadVenueLocation();
    } catch (e) {
      wx.hideLoading();
      wx.showToast({ title: String(e), icon: 'none' });
    }
  },

  formatReviewTime(m) {
    const raw = (m && (m.ended_at || m.score_review_since || m.started_at)) || '';
    if (!raw) return '-';
    return String(raw).slice(0, 19).replace('T', ' ');
  },

  mapPendingMatches(matches) {
    const reviewed = this._reviewedOps || {};
    return (matches || [])
      .filter((m) => {
        const mk = `match:${m.id}`;
        const hasBonus = m.bonus_review_queue && m.bonus_review_queue.length;
        return m.status === 'pending_review' || hasBonus || reviewed[mk];
      })
      .map((m) => {
        const mk = `match:${m.id}`;
        let matchReviewState = reviewed[mk] || '';
        if (!matchReviewState && m.status === 'pending_review') matchReviewState = 'pending';
        if (!matchReviewState && m.reviewed_at && m.status === 'finished') matchReviewState = 'approved';

        const bonusQueue = (m.bonus_review_queue || []).map((b) => {
          const bid = b.bonus_id || b.id;
          const bk = `bonus:${m.id}:${bid}`;
          const bonusRec = (m.bonuses || []).find((x) => x.id === bid);
          let reviewState = reviewed[bk] || 'pending';
          if (!reviewed[bk] && bonusRec) {
            if (bonusRec.status === 'applied') reviewState = 'approved';
            else if (bonusRec.status === 'review_rejected') reviewState = 'rejected';
            else if (bonusRec.status === 'cheat_rejected') reviewState = 'cheat';
          }
          const who = b.user_id === m.player1_id
            ? (m.p1_name || m.player1_name)
            : (b.user_id === m.player2_id ? (m.p2_name || m.player2_name) : '');
          return {
            ...b,
            bonus_id: bid,
            id: bid,
            user_name: who || b.user_name || '选手',
            type_label: b.type === 'break_run' ? '炸清' : b.type === 'clearance' ? '接清' : (b.label || b.type),
            review_time: String(b.created_at || '').slice(0, 19).replace('T', ' ') || '-',
            review_state: reviewState,
          };
        });

        return {
          ...m,
          player1_name: m.p1_name || m.player1_name || '球友1',
          player2_name: m.p2_name || m.player2_name || '球友2',
          status_label: STATUS_ZH[m.status] || m.status,
          review_time: this.formatReviewTime(m),
          match_review_state: matchReviewState,
          bonus_pending: bonusQueue,
        };
      });
  },

  async loadReview() {
    const [matches, exchanges] = await Promise.all([
      adminApi.adminRequest('/api/admin/matches'),
      adminApi.adminRequest('/api/admin/exchanges'),
    ]);
    const pendingMatches = this.mapPendingMatches(matches);
    const pendingEx = (exchanges || []).filter((x) => x.status === 'pending').map((x) => ({
      ...x,
      user_name: x.nickname || x.user_name || '球友',
    }));
    this.setData({
      pendingMatches,
      pendingExchanges: pendingEx,
      reviewedOps: { ...(this._reviewedOps || {}) },
    });
  },

  switchReviewTab(e) {
    const tab = e.currentTarget.dataset.tab;
    this.setData({ reviewTab: tab });
    if (tab === 'logs') this.loadReviewLogs();
  },

  async loadReviewLogs() {
    try {
      const rows = await adminApi.adminRequest('/api/admin/review-logs?limit=200');
      this.setData({
        reviewLogList: (rows || []).map((r) => ({
          ...r,
          time_label: (r.created_at || '').slice(0, 19).replace('T', ' '),
          result_display: r.auto_approved ? '自动通过' : (r.result_label || r.result),
          pts_label: r.points_delta ? `${r.points_delta > 0 ? '+' : ''}${r.points_delta}` : '-',
        })),
      });
    } catch (e) {
      wx.showToast({ title: String(e), icon: 'none' });
      this.setData({ reviewLogList: [] });
    }
  },

  reReviewLog(e) {
    const { id, action } = e.currentTarget.dataset;
    const labels = { approve: '通过', reject: '驳回', cheat: '认定作弊' };
    wx.showModal({
      title: '重新审核',
      content: `确定改为「${labels[action] || action}」？`,
      success: async (res) => {
        if (!res.confirm) return;
        wx.showLoading({ title: '处理中...', mask: true });
        try {
          await adminApi.adminRequest(
            `/api/admin/review-logs/${encodeURIComponent(id)}/re-review`,
            'POST',
            { action, note: '' },
          );
          wx.hideLoading();
          wx.showToast({ title: '已更新', icon: 'success' });
          this.loadReviewLogs();
          if (this.data.reviewTab === 'match') this.loadReview();
        } catch (err) {
          wx.hideLoading();
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  async toggleUserAutoReview(e) {
    const { id, kind } = e.currentTarget.dataset;
    const u = (this.data.userList || []).find((x) => x.id === id);
    if (!u || !this.data.canWrite) return;
    const body = {};
    if (kind === 'bonus') body.auto_review_bonus = !u.auto_review_bonus;
    else body.auto_review_shutout = !u.auto_review_shutout;
    wx.showLoading({ title: '保存中...', mask: true });
    try {
      const r = await adminApi.adminRequest(
        `/api/admin/user/${encodeURIComponent(id)}/review-auto-flags`,
        'PUT',
        body,
      );
      wx.hideLoading();
      wx.showToast({ title: '已保存', icon: 'success' });
      this.setData({
        userList: (this.data.userList || []).map((x) => (x.id === id ? { ...x, ...r } : x)),
      });
    } catch (err) {
      wx.hideLoading();
      wx.showToast({ title: String(err), icon: 'none' });
    }
  },

  async loadMatches() {
    const list = await adminApi.adminRequest('/api/admin/matches');
    const reviewed = this._reviewedOps || {};
    const matchList = (list || []).map((m) => {
      const mk = `match:${m.id}`;
      let matchReviewState = reviewed[mk] || '';
      if (!matchReviewState && m.status === 'pending_review') matchReviewState = 'pending';
      if (!matchReviewState && m.reviewed_at) matchReviewState = 'approved';
      return {
        ...m,
        review_time: this.formatReviewTime(m),
        match_review_state: matchReviewState,
        status_label: STATUS_ZH[m.status] || m.status,
      };
    });
    this.setData({ matchList });
  },

  async loadUsers() {
    const list = await adminApi.adminRequest('/api/admin/users');
    this.setData({
      userList: (list || []).map((u) => ({
        ...u,
        adminRoleLabel: u.venue_admin_role === 'owner'
          ? '主管理员'
          : (u.venue_admin_role === 'admin' ? '子管理员' : ''),
      })),
    });
  },

  async loadTables() {
    const list = await adminApi.adminRequest('/api/admin/tables');
    this.setData({ tableList: list || [] });
  },

  async loadLadder() {
    const payload = await adminApi.adminRequest('/api/admin/settings/ladder');
    const rules = payload.rules || payload;
    const isGlobal = payload.scope === 'global';
    const sections = ladderForm.buildFormFromRules(rules, {
      includeTiers: isGlobal,
      includeIdle: isGlobal,
    });
    let tip = isGlobal
      ? '全平台默认天梯规则（与各球房同步基准）'
      : (payload.venue_readonly_tip || '俱乐部仅可查看总后台规则说明，不可修改');
    this.setData({
      ladderSections: isGlobal ? sections : [],
      ladderRules: { ...rules },
      ladderTip: tip,
      ladderDesc: payload.description || '',
      ladderHasCustom: !!payload.has_custom_rules,
      ladderIsGlobal: isGlobal,
      canLadder: isGlobal && this.data.canLadder,
    });
  },

  onLadderInput(e) {
    const key = e.currentTarget.dataset.key;
    const val = e.detail.value;
    this.setData({
      ladderSections: ladderForm.onFieldInput(this.data.ladderSections, key, val),
    });
  },

  async saveLadder() {
    wx.showLoading({ title: '保存中...', mask: true });
    try {
      const body = ladderForm.collectBody(
        this.data.ladderSections,
        this.data.ladderRules,
        { includeTiers: this.data.ladderIsGlobal, includeIdle: this.data.ladderIsGlobal },
      );
      await adminApi.adminRequest('/api/admin/settings/ladder', 'PUT', body);
      wx.hideLoading();
      wx.showToast({ title: '已保存', icon: 'success' });
      this.loadLadder();
    } catch (e) {
      wx.hideLoading();
      wx.showToast({ title: String(e), icon: 'none' });
    }
  },

  async syncLadder() {
    wx.showLoading({ title: '同步中...', mask: true });
    try {
      await adminApi.adminRequest('/api/admin/settings/ladder/sync', 'POST', {});
      wx.hideLoading();
      wx.showToast({ title: '已同步', icon: 'success' });
      this.loadLadder();
    } catch (e) {
      wx.hideLoading();
      wx.showToast({ title: String(e), icon: 'none' });
    }
  },

  switchVenueTab(e) {
    const tab = e.currentTarget.dataset.tab || 'list';
    this.setData({ venueTab: tab });
    if (tab === 'apply') this.loadVenueApplications();
    else if (tab === 'deleted') this.loadDeletedVenueList();
    else this.loadVenueList();
  },

  async loadVenues() {
    await Promise.all([this.loadVenueList(), this.loadVenueApplications(), this.loadDeletedVenueList()]);
  },

  async loadDeletedVenueList() {
    const list = await adminApi.adminRequest('/api/admin/venues/deleted');
    this.setData({
      deletedVenueList: (list || []).map((v) => ({
        ...v,
        deletedShort: (v.deleted_at || '').slice(0, 19).replace('T', ' ') || '-',
      })),
    });
  },

  async loadVenueList() {
    const list = await adminApi.adminRequest('/api/admin/venues');
    this.setData({
      venueList: (list || []).map((v) => ({
        ...v,
        expShort: (v.member_expires_at || '').slice(0, 10) || '-',
      })),
    });
  },

  async loadVenueApplications() {
    const list = await adminApi.adminRequest('/api/admin/venue-applications');
    const pending = (list || []).filter((a) => a.status === 'pending');
    this.setData({ venueAppList: pending.length ? pending : (list || []) });
  },

  async approveVenueApp(e) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({
      title: '通过申请',
      content: '确定通过并创建俱乐部账号？',
      success: async (res) => {
        if (!res.confirm) return;
        wx.showLoading({ title: '处理中...', mask: true });
        try {
          await adminApi.adminRequest(`/api/admin/venue-applications/${id}/approve`, 'POST', {});
          wx.hideLoading();
          wx.showToast({ title: '已通过', icon: 'success' });
          this.loadVenues();
        } catch (err) {
          wx.hideLoading();
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  rejectVenueApp(e) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({
      title: '拒绝原因',
      editable: true,
      placeholderText: '可选',
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await adminApi.adminRequest(`/api/admin/venue-applications/${id}/reject`, 'POST', {
            reason: res.content || '',
          });
          wx.showToast({ title: '已拒绝', icon: 'success' });
          this.loadVenueApplications();
        } catch (err) {
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  addVenue() {
    wx.showModal({
      title: '俱乐部名称',
      editable: true,
      placeholderText: '必填',
      success: (res1) => {
        if (!res1.confirm || !res1.content) return;
        const name = res1.content.trim();
        wx.showModal({
          title: '登录手机号',
          editable: true,
          placeholderText: '11位，作登录账号',
          success: async (res2) => {
            if (!res2.confirm || !res2.content) return;
            wx.showModal({
              title: '登录密码',
              editable: true,
              placeholderText: '至少6位',
              success: async (res3) => {
                if (!res3.confirm || !res3.content) return;
                wx.showLoading({ title: '创建中...', mask: true });
                try {
                  await adminApi.adminRequest('/api/admin/venues', 'POST', {
                    name,
                    username: res2.content.trim(),
                    password: res3.content,
                    security_code: res3.content.slice(-6),
                    member_expires_at: new Date(Date.now() + 365 * 86400000).toISOString().slice(0, 19),
                  });
                  wx.hideLoading();
                  wx.showToast({ title: '已创建', icon: 'success' });
                  this.setData({ venueTab: 'list' });
                  this.loadVenueList();
                } catch (err) {
                  wx.hideLoading();
                  wx.showToast({ title: String(err), icon: 'none' });
                }
              },
            });
          },
        });
      },
    });
  },

  viewVenueDetail(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) return;
    wx.showLoading({ title: '加载...', mask: true });
    adminApi.adminRequest(`/api/admin/venues/${encodeURIComponent(id)}/detail`)
      .then((d) => {
        wx.hideLoading();
        const v = d.venue || {};
        const pwd = v.initial_password_plain
          ? v.initial_password_plain
          : (v.has_password ? '(已设置，未保存明文)' : '-');
        const tables = (d.tables || []).map((t) => ({
          id: t.id,
          label: (t.number || t.id || '-') + (t.name ? ` · ${t.name}` : ''),
          status: t.opened ? '已开台' : '未开台',
        }));
        const members = (d.members || []).slice(0, 50).map((m) => ({
          id: m.id,
          nickname: m.nickname || '-',
          score: m.score != null ? m.score : 0,
          tier: m.tier_name || '-',
          record: `${m.wins || 0}/${m.losses || 0}`,
        }));
        this.setData({
          venueDetailVisible: true,
          venueDetail: {
            name: v.name || '球房',
            manager_name: v.manager_name || '-',
            username: v.username || '-',
            password: pwd,
            phone: v.apply_phone || v.contact_phone || '-',
            expires: (v.member_expires_at || '').slice(0, 10) || '-',
            is_active: !!v.is_member_active,
            table_count: v.table_count != null ? v.table_count : tables.length,
            member_count: v.member_count != null ? v.member_count : members.length,
            total_score: d.total_member_score != null ? d.total_member_score : 0,
            apply_source: v.apply_source === 'mp_apply' ? '小程序申请' : (v.apply_source || '-'),
            tables,
            members,
          },
        });
      })
      .catch((err) => {
        wx.hideLoading();
        wx.showToast({ title: String(err), icon: 'none' });
      });
  },

  closeVenueDetail() {
    this.setData({ venueDetailVisible: false, venueDetail: null });
  },

  deleteVenue(e) {
    const id = e.currentTarget.dataset.id;
    const name = e.currentTarget.dataset.name || '';
    wx.showModal({
      title: '删除球房',
      content: `确定删除「${name}」？删除后可到「已删除」中恢复，桌台数据会保留。`,
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await adminApi.adminRequest(`/api/admin/venue/${id}`, 'DELETE');
          wx.showToast({ title: '已删除', icon: 'success' });
          this.loadVenueList();
          this.loadDeletedVenueList();
        } catch (err) {
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  restoreVenue(e) {
    const id = e.currentTarget.dataset.id;
    const name = e.currentTarget.dataset.name || '';
    wx.showModal({
      title: '恢复球房',
      content: `确定恢复「${name}」？恢复后将重新出现在会员列表与小程序。`,
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await adminApi.adminRequest(`/api/admin/venue/${id}/restore`, 'POST');
          wx.showToast({ title: '已恢复', icon: 'success' });
          this.loadVenueList();
          this.loadDeletedVenueList();
        } catch (err) {
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  grantMpSuperWechat(e) {
    const uid = e.currentTarget.dataset.id;
    wx.showModal({
      title: '授权小程序总后台',
      content: '确定授权该玩家微信使用总后台入口？',
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await adminApi.adminRequest('/api/admin/mp-super-wechat-allowlist', 'POST', { user_id: uid });
          wx.showToast({ title: '已授权', icon: 'success' });
          this.loadUsers();
        } catch (err) {
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  editVenueExpire(e) {
    const id = e.currentTarget.dataset.id;
    const venue = (this.data.venueList || []).find((v) => v.id === id);
    if (!venue) return;
    wx.showModal({
      title: '续期天数',
      editable: true,
      placeholderText: '例如 365',
      success: async (res) => {
        if (!res.confirm) return;
        const days = parseInt(res.content, 10);
        if (!days || days < 1) {
          wx.showToast({ title: '请输入有效天数', icon: 'none' });
          return;
        }
        const exp = new Date();
        exp.setDate(exp.getDate() + days);
        const iso = exp.toISOString().slice(0, 19);
        try {
          await adminApi.adminRequest(`/api/admin/venue/${id}`, 'PUT', {
            member_expires_at: iso,
          });
          wx.showToast({ title: '已续期', icon: 'success' });
          this.loadVenues();
        } catch (err) {
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  async loadProducts() {
    const list = await adminApi.adminRequest('/api/admin/products');
    this.setData({ productList: list || [] });
  },

  async loadExchanges() {
    const list = await adminApi.adminRequest('/api/admin/exchanges');
    this.setData({ exchangeList: list || [] });
  },

  async loadLogs() {
    const list = await adminApi.adminRequest('/api/admin/logs/score');
    this.setData({ logList: (list || []).slice(0, 100) });
  },

  async loadStaff() {
    const staff = await adminApi.adminRequest('/api/admin/staff');
    this.setData({ staffList: staff || [] });
    if (this.data.canPromotePlayers) {
      await this.loadPlayersForStaff();
    }
  },

  markReviewed(key, state) {
    this._reviewedOps = this._reviewedOps || {};
    this._reviewedOps[key] = state;
    this.setData({ reviewedOps: { ...this._reviewedOps } });
  },

  async reviewMatch(e) {
    const { id, action } = e.currentTarget.dataset;
    wx.showLoading({ title: '处理中...', mask: true });
    try {
      await adminApi.adminRequest(`/api/admin/match/${id}/review`, 'POST', { action });
      this.markReviewed(`match:${id}`, action === 'approve' ? 'approved' : 'rejected');
      wx.hideLoading();
      wx.showToast({ title: action === 'approve' ? '已通过' : '已驳回', icon: 'success' });
      this.loadModule();
    } catch (err) {
      wx.hideLoading();
      wx.showToast({ title: String(err), icon: 'none' });
    }
  },

  async reviewBonus(e) {
    const { id, bonusId, action } = e.currentTarget.dataset;
    if (!bonusId) {
      wx.showToast({ title: '缺少审核项编号', icon: 'none' });
      return;
    }
    wx.showLoading({ title: '处理中...', mask: true });
    try {
      await adminApi.adminRequest(`/api/admin/match/${id}/bonus-review`, 'POST', {
        action,
        bonus_id: bonusId,
      });
      const state = action === 'approve' ? 'approved' : action === 'cheat' ? 'cheat' : 'rejected';
      this.markReviewed(`bonus:${id}:${bonusId}`, state);
      wx.hideLoading();
      wx.showToast({ title: state === 'approved' ? '已通过' : '已处理', icon: 'success' });
      this.loadModule();
    } catch (err) {
      wx.hideLoading();
      wx.showToast({ title: String(err), icon: 'none' });
    }
  },

  async reviewExchange(e) {
    const { id, status } = e.currentTarget.dataset;
    wx.showLoading({ title: '处理中...', mask: true });
    try {
      await adminApi.adminRequest(`/api/admin/exchange/${id}/review`, 'POST', { status });
      wx.hideLoading();
      wx.showToast({ title: status === 'approved' ? '已通过' : '已拒绝', icon: 'success' });
      this.loadModule();
    } catch (err) {
      wx.hideLoading();
      wx.showToast({ title: String(err), icon: 'none' });
    }
  },

  async deleteMatch(e) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({
      title: '确认删除对局？',
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await adminApi.adminRequest(`/api/admin/match/${encodeURIComponent(id)}`, 'DELETE');
          wx.showToast({ title: '已删除', icon: 'success' });
          this.loadMatches();
        } catch (err) {
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  adjustScore(e) {
    const uid = e.currentTarget.dataset.id;
    wx.showModal({
      title: '调整积分',
      editable: true,
      placeholderText: '正数加分，负数扣分',
      success: async (res) => {
        if (!res.confirm) return;
        const n = parseInt(res.content, 10);
        if (Number.isNaN(n) || n === 0) {
          wx.showToast({ title: '请输入非零整数', icon: 'none' });
          return;
        }
        try {
          await adminApi.adminRequest(`/api/admin/user/${encodeURIComponent(uid)}/score`, 'POST', {
            delta: n,
            reason: '管理员调整',
          });
          wx.showToast({ title: '已调整', icon: 'success' });
          this.loadUsers();
        } catch (err) {
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  punishUser(e) {
    const { id, action } = e.currentTarget.dataset;
    wx.showModal({
      title: '封禁玩家',
      content: '确定封禁该玩家？',
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await adminApi.adminRequest(`/api/admin/user/${encodeURIComponent(id)}/punish`, 'POST', {
            action: action || 'ban',
            reason: '管理员处罚',
            public: true,
          });
          wx.showToast({ title: '已处理', icon: 'success' });
          this.loadUsers();
        } catch (err) {
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  deleteUser(e) {
    const uid = e.currentTarget.dataset.id;
    wx.showModal({
      title: '确认删除玩家？',
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await adminApi.adminRequest(`/api/admin/user/${encodeURIComponent(uid)}`, 'DELETE');
          wx.showToast({ title: '已删除', icon: 'success' });
          this.loadUsers();
        } catch (err) {
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  addTable() {
    wx.showModal({
      title: '新增桌台',
      editable: true,
      placeholderText: '桌台名称',
      success: async (res) => {
        if (!res.confirm || !res.content) return;
        try {
          await adminApi.adminRequest('/api/admin/tables', 'POST', { name: res.content.trim() });
          wx.showToast({ title: '已添加', icon: 'success' });
          this.loadTables();
        } catch (err) {
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  async toggleTableOpen(e) {
    const id = e.currentTarget.dataset.id;
    const t = (this.data.tableList || []).find((x) => x.id === id);
    if (!t) return;
    try {
      await adminApi.adminRequest(`/api/admin/table/${id}/open`, 'POST', {
        opened: !t.opened,
        hours: 4,
      });
      wx.showToast({ title: t.opened ? '已关台' : '已开台', icon: 'success' });
      this.loadTables();
    } catch (err) {
      wx.showToast({ title: String(err), icon: 'none' });
    }
  },

  async releaseTable(e) {
    const id = e.currentTarget.dataset.id;
    try {
      await adminApi.adminRequest(`/api/admin/table/${id}/release`, 'POST', {});
      wx.showToast({ title: '已释放', icon: 'success' });
      this.loadTables();
    } catch (err) {
      wx.showToast({ title: String(err), icon: 'none' });
    }
  },

  deleteTable(e) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({
      title: '确认删除桌台？',
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await adminApi.adminRequest(`/api/admin/table/${id}`, 'DELETE');
          wx.showToast({ title: '已删除', icon: 'success' });
          this.loadTables();
        } catch (err) {
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  deleteProduct(e) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({
      title: '确认删除商品？',
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await adminApi.adminRequest(`/api/admin/product/${id}`, 'DELETE');
          wx.showToast({ title: '已删除', icon: 'success' });
          this.loadProducts();
        } catch (err) {
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  deleteLog(e) {
    const id = e.currentTarget.dataset.id;
    wx.showModal({
      title: '确认删除记录？',
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await adminApi.adminRequest(`/api/admin/log/score/${encodeURIComponent(id)}`, 'DELETE');
          wx.showToast({ title: '已删除', icon: 'success' });
          this.loadLogs();
        } catch (err) {
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  async inviteStaff() {
    wx.showLoading({ title: '生成中...', mask: true });
    try {
      const qr = await adminApi.adminRequest('/api/mp-admin/staff/invite-qr', 'POST', {});
      wx.hideLoading();
      this.setData({ inviteQr: qr.qr_base64 || '' });
      wx.showModal({
        title: '邀请码已生成',
        content: `请新管理员在「管理后台登录」页扫一扫，有效期 ${Math.floor((qr.expires_in || 300) / 60)} 分钟`,
        showCancel: false,
      });
    } catch (e) {
      wx.hideLoading();
      wx.showToast({ title: String(e), icon: 'none' });
    }
  },

  removeStaff(e) {
    const { id, name } = e.currentTarget.dataset;
    wx.showModal({
      title: '确认移除',
      content: `确定移除 ${name || '该管理员'}？`,
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await adminApi.adminRequest(`/api/admin/staff/${id}`, 'DELETE');
          wx.showToast({ title: '已移除', icon: 'success' });
          this.loadStaff();
        } catch (err) {
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  async loadPlayersForStaff() {
    try {
      const list = await adminApi.adminRequest('/api/admin/users');
      const players = (list || []).filter((u) => u.can_promote);
      this.setData({ playerPickList: players });
    } catch (e) {
      wx.showToast({ title: String(e), icon: 'none' });
    }
  },

  openModuleShortcut(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) return;
    const locked = (this.data.disabledModuleIds || []).indexOf(id) >= 0;
    if (locked) {
      wx.showToast({ title: '会员已到期，请续费后使用', icon: 'none' });
      return;
    }
    wx.navigateTo({ url: `/pages/admin-module/admin-module?m=${encodeURIComponent(id)}` });
  },

  async loadMpWechatAllowlist() {
    const list = await adminApi.adminRequest('/api/admin/mp-super-wechat-allowlist');
    this.setData({
      mpAllowList: (list || []).map((row) => {
        const av = row.avatar || '';
        const usable = av.startsWith('http://') || av.startsWith('https://');
        return {
          ...row,
          avatarUsable: usable,
          initial: (row.nickname || '?').slice(0, 1),
        };
      }),
    });
  },

  async genMpAllowQr() {
    wx.showLoading({ title: '生成中...', mask: true });
    try {
      const qr = await adminApi.adminRequest('/api/admin/mp-super-wechat-allowlist/register-qr', 'POST', {});
      wx.hideLoading();
      if (qr.qr_base64) {
        this.setData({ mpAllowQr: qr.qr_base64 });
        wx.previewImage({ urls: [qr.qr_base64], current: qr.qr_base64 });
      }
      wx.showModal({
        title: '授权登记码',
        content: qr.hint || '请对方先微信登录小程序，再扫此码',
        showCancel: false,
      });
    } catch (e) {
      wx.hideLoading();
      wx.showToast({ title: String(e), icon: 'none' });
    }
  },

  removeMpAllow(e) {
    const oid = e.currentTarget.dataset.oid;
    wx.showModal({
      title: '移除授权',
      content: '确定移除该微信的总后台入口授权？',
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await adminApi.adminRequest(`/api/admin/mp-super-wechat-allowlist/${encodeURIComponent(oid)}`, 'DELETE');
          wx.showToast({ title: '已移除', icon: 'success' });
          this.loadMpWechatAllowlist();
        } catch (err) {
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  loadSettings() {
    return Promise.resolve();
  },

  changeAdminPassword() {
    wx.showModal({
      title: '当前密码',
      editable: true,
      placeholderText: '总后台当前密码',
      success: (res1) => {
        if (!res1.confirm) return;
        wx.showModal({
          title: '新密码',
          editable: true,
          placeholderText: '至少6位',
          success: (res2) => {
            if (!res2.confirm) return;
            wx.showModal({
              title: '确认新密码',
              editable: true,
              success: async (res3) => {
                if (!res3.confirm) return;
                wx.showLoading({ title: '保存中...', mask: true });
                try {
                  await adminApi.adminRequest('/api/admin/password/change', 'POST', {
                    old_password: res1.content,
                    new_password: res2.content,
                    confirm_password: res3.content,
                  });
                  wx.hideLoading();
                  wx.showToast({ title: '密码已更新', icon: 'success' });
                } catch (err) {
                  wx.hideLoading();
                  wx.showToast({ title: String(err), icon: 'none' });
                }
              },
            });
          },
        });
      },
    });
  },

  resetSystemData() {
    wx.showModal({
      title: '危险操作',
      content: '将清空全平台玩家、对局、积分日志等（保留球房与规则配置）。确定继续？',
      success: (res1) => {
        if (!res1.confirm) return;
        wx.showModal({
          title: '总后台账号',
          editable: true,
          placeholderText: '登录账号',
          success: (res2) => {
            if (!res2.confirm) return;
            wx.showModal({
              title: '总后台密码',
              editable: true,
              placeholderText: '确认身份',
              success: async (res3) => {
                if (!res3.confirm) return;
                wx.showLoading({ title: '重置中...', mask: true });
                try {
                  await adminApi.adminRequest('/api/admin/system/reset', 'POST', {
                    username: res2.content.trim(),
                    password: res3.content,
                  });
                  wx.hideLoading();
                  wx.showToast({ title: '已重置', icon: 'success' });
                } catch (err) {
                  wx.hideLoading();
                  wx.showToast({ title: String(err), icon: 'none' });
                }
              },
            });
          },
        });
      },
    });
  },

  promotePlayer(e) {
    const { id, name } = e.currentTarget.dataset;
    wx.showModal({
      title: '设为子管理员',
      content: `确定将「${name || '该玩家'}」设为子管理员？对方需已用微信登录过小程序，最多3人。`,
      success: async (res) => {
        if (!res.confirm) return;
        wx.showLoading({ title: '处理中...', mask: true });
        try {
          await adminApi.adminRequest(
            `/api/admin/user/${encodeURIComponent(id)}/promote-admin`,
            'POST',
            {},
          );
          wx.hideLoading();
          wx.showToast({ title: '已设为子管理员', icon: 'success' });
          this.loadStaff();
          this.loadPlayersForStaff();
          if (this.data.module === 'users') this.loadUsers();
        } catch (err) {
          wx.hideLoading();
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },

  demotePlayer(e) {
    const { id, name } = e.currentTarget.dataset;
    wx.showModal({
      title: '取消子管理员',
      content: `确定取消「${name || '该玩家'}」的子管理员身份？`,
      success: async (res) => {
        if (!res.confirm) return;
        wx.showLoading({ title: '处理中...', mask: true });
        try {
          await adminApi.adminRequest(
            `/api/admin/user/${encodeURIComponent(id)}/demote-admin`,
            'POST',
            {},
          );
          wx.hideLoading();
          wx.showToast({ title: '已取消', icon: 'success' });
          this.loadStaff();
          this.loadPlayersForStaff();
          if (this.data.module === 'users') this.loadUsers();
        } catch (err) {
          wx.hideLoading();
          wx.showToast({ title: String(err), icon: 'none' });
        }
      },
    });
  },
});
