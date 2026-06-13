const api = require('../../utils/api');
const { getApiBaseUrl } = require('../../utils/config');
const { parseTableScanResult } = require('../../utils/tableQr');
const { resolveTableQr, applyResolvedVenue, formatScanError } = require('../../utils/tableScanApi');
const { attachLoginHandlers } = require('../../utils/loginHelper');
const {
  decorateList,
  padLeaderboardTop,
  buildChallengeSlots,
} = require('../../utils/rank');

const HOME_REFRESH_MS = 12000;
const { getTierStyle } = require('../../utils/tierIcons');
const {
  getVenueId,
  isManualPick,
  setVenueId,
  clearManualPick,
} = require('../../utils/venueStore');
const {
  ensureLocation,
  pickVenueFromList,
  buildDistanceState,
  enrichVenuesWithDistance,
  WARN_M,
} = require('../../utils/locationHelper');
const app = getApp();

Page({
  data: {
    loggedIn: false,
    topRank: [],
    tables: [],
    challengeSlots: [],
    challengeHint: '',
    myRank: 9999,
    todayScore: 0,
    rankedRemainingDaily: 0,
    netError: '',
    apiUrl: '',
    playerDetail: null,
    venueId: '',
    venueName: '',
    venueLocating: true,
    venueLocateFail: false,
    venueManual: false,
    distanceText: '',
    distanceWarning: false,
    venueList: [],
    statusBarHeight: 20,
    navBarHeight: 64,
    navContentHeight: 44,
    showQrLogin: false,
    qrScanHint: false,
    logging: false,
    showAuthFallback: false,
    pendingNickname: '',
    pendingAvatar: '',
    agreedToTerms: false,
  },

  onLoad() {
    const sys = wx.getSystemInfoSync();
    const menu = wx.getMenuButtonBoundingClientRect();
    const statusBarHeight = sys.statusBarHeight || 20;
    const navContentHeight = (menu.top - statusBarHeight) * 2 + menu.height;
    const navBarHeight = statusBarHeight + navContentHeight;
    this.setData({ statusBarHeight, navBarHeight, navContentHeight });
    attachLoginHandlers(this, () => this.onQrLoginSuccess());
  },

  onShow() {
    const loggedIn = !!app.globalData.token;
    this.setData({
      loggedIn,
      apiUrl: app.globalData.baseUrl || getApiBaseUrl(),
    });
    this.initVenueBar()
      .then(() => this.handleQrEntry())
      .then(() => this.loadData());
    this.startHomeRefresh();
  },

  /** 微信扫桌台码冷启动：先入首页，老用户静默登录，新用户引导授权 */
  async handleQrEntry() {
    const pending = app.globalData.pendingTableScan;
    if (!pending || !pending.tableId || !pending.qrToken) return;
    app.globalData.pendingTableScan = null;

    try {
      const info = await resolveTableQr(pending.tableId, pending.qrToken);
      applyResolvedVenue(info);
      await this.initVenueBar();
    } catch (e) {
      console.warn('[QR entry] resolve venue failed', e);
    }

    if (app.globalData.token) {
      this.setData({ loggedIn: true, qrScanHint: true });
      return;
    }

    const refresh = wx.getStorageSync('refresh_token');
    if (refresh) {
      try {
        await api.tryRefreshToken();
        await api.login();
        this.setData({ loggedIn: true, qrScanHint: true });
        return;
      } catch (e) {
        console.warn('[QR entry] refresh login failed', e);
      }
    }

    if (api.hasWxProfileAuthorized()) {
      try {
        await api.wechatLoginSilent();
        this.setData({ loggedIn: true, qrScanHint: true });
        return;
      } catch (e) {
        console.warn('[QR entry] silent login failed', e);
      }
    }

    this.setData({ showQrLogin: true, qrScanHint: true });
  },

  onQrLoginSuccess() {
    this.setData({
      showQrLogin: false,
      loggedIn: true,
      logging: false,
      showAuthFallback: false,
      qrScanHint: true,
    });
    this.loadData();
  },

  onHide() {
    this.stopHomeRefresh();
  },

  startHomeRefresh() {
    this.stopHomeRefresh();
    this._homeRefreshTimer = setInterval(() => {
      this.loadData(true);
    }, HOME_REFRESH_MS);
  },

  stopHomeRefresh() {
    if (this._homeRefreshTimer) {
      clearInterval(this._homeRefreshTimer);
      this._homeRefreshTimer = null;
    }
  },

  initVenueBar() {
    this.setData({ venueLocating: true, venueLocateFail: false });
    return app
      .ensureLocation()
      .then((loc) => this.fetchVenues(loc).then((venues) => ({ venues, loc })))
      .catch(() => this.fetchVenues(null).then((venues) => ({ venues, loc: null })))
      .then(({ venues, loc }) => {
        if (!venues.length) {
          this.setData({
            venueLocating: false,
            venueLocateFail: true,
            venueName: '暂无球房',
          });
          return;
        }
        const list = enrichVenuesWithDistance(venues, loc);
        const manual = isManualPick();
        const storedId = getVenueId();
        let selected = pickVenueFromList(list, storedId, manual);
        if (!manual && selected) {
          setVenueId(selected.id, false);
        } else if (selected) {
          app.globalData.venueId = selected.id;
        }
        const dist = buildDistanceState(selected, loc);
        this.setData({
          venueLocating: false,
          venueLocateFail: !loc,
          venueId: selected.id,
          venueName: selected.name,
          venueManual: manual,
          venueList: list,
          distanceText: dist.distanceText,
          distanceWarning: dist.distanceWarning,
        });
        if (dist.distanceWarning && !this._distanceModalShown) {
          this._distanceModalShown = true;
          this.showDistanceWarning(selected.name, dist.distanceM);
        }
      })
      .catch(() => {
        this.setData({
          venueLocating: false,
          venueLocateFail: true,
          venueName: '定位失败',
        });
      });
  },

  fetchVenues(loc) {
    let q = '';
    if (loc) {
      q = `?latitude=${loc.latitude}&longitude=${loc.longitude}`;
    }
    return api.request(`/api/venues/list${q}`).then((data) => data.venues || []);
  },

  showDistanceWarning(name, meters) {
    const m = meters != null ? meters : WARN_M + 1;
    wx.showModal({
      title: '距离提示',
      content: `您当前位置距「${name}」约 ${m} 米，已超过 ${WARN_M} 米。若定位不准，请点击上方球房名称手动选择。`,
      showCancel: false,
      confirmText: '知道了',
    });
  },

  onTapVenueBar() {
    const list = this.data.venueList || [];
    if (!list.length) {
      wx.showToast({ title: '暂无球房列表', icon: 'none' });
      return;
    }
    const names = list.map((v) => {
      if (v.distance_m != null) return `${v.name}（${v.distance_m}米）`;
      return v.name;
    });
    wx.showActionSheet({
      itemList: names,
      success: (res) => {
        const venue = list[res.tapIndex];
        if (!venue) return;
        setVenueId(venue.id, true);
        const loc = app.globalData.location;
        const dist = buildDistanceState(venue, loc);
        this.setData({
          venueId: venue.id,
          venueName: venue.name,
          venueManual: true,
          distanceText: dist.distanceText,
          distanceWarning: dist.distanceWarning,
        });
        if (dist.distanceWarning) {
          this._distanceModalShown = true;
          this.showDistanceWarning(venue.name, dist.distanceM);
        }
        this.loadData();
      },
    });
  },

  onRetryLocate() {
    app.globalData.location = null;
    this._distanceModalShown = false;
    clearManualPick();
    this.initVenueBar().then(() => this.loadData());
  },

  retryNetwork() {
    app.globalData.baseUrl = getApiBaseUrl();
    this.setData({ apiUrl: app.globalData.baseUrl, netError: '' });
    this.loadData();
  },

  goProfile() {
    wx.switchTab({ url: '/pages/profile/profile' });
  },

  loadData(silent) {
    const self = this;
    const reqId = (this._loadSeq || 0) + 1;
    this._loadSeq = reqId;
    const venueId = getVenueId();
    const venueQ = venueId ? `?venue_id=${encodeURIComponent(venueId)}` : '';
    return api
      .ping()
      .then(() => {
        if (self._loadSeq !== reqId) return null;
        if (!silent) self.setData({ netError: '' });
        return api.request(`/api/home/summary${venueQ}`);
      })
      .then((data) => {
        if (!data || self._loadSeq !== reqId) return;
        const topRank = padLeaderboardTop(decorateList(data.top_rank || []), 10, 'club_rank');
        const myRank = data.my_rank != null ? data.my_rank : 9999;
        const rmin = data.challenge_rank_min != null ? data.challenge_rank_min : 1;
        const rmax = data.challenge_rank_max != null ? data.challenge_rank_max : 5;
        const loggedIn = !!app.globalData.token;
        const challengeSlots = loggedIn
          ? buildChallengeSlots(data.challenge_targets || [], myRank, { rmin, rmax })
          : [];
        let challengeHint = '';
        if (loggedIn && myRank >= 9999) {
          challengeHint = '您暂无天梯排名，完成对局后可挑战更高名次选手';
        }
        self.setData({
          loggedIn,
          topRank,
          tables: data.tables || [],
          challengeSlots,
          challengeHint,
          myRank,
          todayScore: data.today_score || 0,
          rankedRemainingDaily: data.ranked_remaining_daily ?? 0,
        });
      })
      .catch((e) => {
        if (silent) return;
        const msg = typeof e === 'string' ? e : '网络连接失败';
        self.setData({ netError: msg });
      });
  },

  ensureLogin() {
    if (!app.globalData.token) {
      wx.showToast({ title: '请先在「我的」完成微信授权登录', icon: 'none', duration: 2500 });
      return Promise.resolve(false);
    }
    return Promise.resolve(true);
  },

  scanTable() {
    if (this.data.distanceWarning) {
      wx.showModal({
        title: '请确认球房',
        content: `您距「${this.data.venueName}」超过 ${WARN_M} 米，确定仍在本店扫码开台？`,
        success: (r) => {
          if (r.confirm) this.doScanTable();
        },
      });
      return;
    }
    this.doScanTable();
  },

  doScanTable() {
    wx.scanCode({
      onlyFromCamera: true,
      scanType: ['qrCode', 'wxCode'],
      success: (res) => {
        const parsed = parseTableScanResult(res.result || res.path || '');
        if (!parsed) {
          wx.showToast({ title: '请扫描球台完整二维码', icon: 'none', duration: 2500 });
          return;
        }
        const { tableId, qrToken } = parsed;
        if (!tableId || !qrToken) {
          wx.showToast({ title: '二维码无效，请重新扫描', icon: 'none' });
          return;
        }
        resolveTableQr(tableId, qrToken)
          .then((info) => {
            const venueId = applyResolvedVenue(info);
            wx.navigateTo({
              url: `/pages/table/table?table_id=${encodeURIComponent(tableId)}&qr_token=${encodeURIComponent(qrToken)}&venue_id=${encodeURIComponent(venueId)}`,
            });
          })
          .catch((err) => {
            wx.showModal({
              title: '无法扫码',
              content: formatScanError(err),
              showCancel: false,
            });
          });
      },
      fail: (err) => {
        const msg = (err && err.errMsg) || '';
        if (msg.indexOf('cancel') < 0 && msg.indexOf('取消') < 0) {
          wx.showToast({ title: '扫码失败', icon: 'none' });
        }
      },
    });
  },

  goRank() {
    wx.switchTab({ url: '/pages/rank/rank' });
  },

  showPlayer(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) return;
    api
      .request(`/api/rank/player/${id}`)
      .then((p) => {
        this.setData({
          playerDetail: { ...p, ...getTierStyle(p.tier_index) },
        });
      })
      .catch((err) => wx.showToast({ title: err, icon: 'none' }));
  },

  closePlayer() {
    this.setData({ playerDetail: null });
  },

  noop() {},

  onChallengeTap(e) {
    const idx = e.currentTarget.dataset.index;
    const slot = this.data.challengeSlots[idx];
    if (!slot || slot.empty) return;
    this.challenge({ currentTarget: { dataset: { target: slot } } });
  },

  challenge(e) {
    this.ensureLogin().then((ok) => {
      if (!ok) return;
      const target = e.currentTarget.dataset.target;
      wx.showModal({
        title: '发起排位挑战',
        content: `挑战 ${target.nickname}(排名第${target.rank})？需在该桌扫码开始`,
        success: (r) => {
          if (r.confirm) {
            wx.setStorageSync('challenge_target', target);
            this.scanTable();
          }
        },
      });
    });
  },
});
