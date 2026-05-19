const api = require('../../utils/api');

const app = getApp();



const BONUS_LABEL = { break_run: '炸清+20', clearance: '接清+15' };



Page({

  data: {

    tableId: '',

    qrToken: '',

    table: null,

    match: null,

    raceTo: 5,

    racePickerIndex: 0,

    matchType: 'casual',

    cooldown: 0,

    cooldownTimer: null,

    pendingBonuses: [],

    opponentBonusCard: null,

    pollTimer: null,
    loadError: '',
    pageReady: false,
    _initDone: false,

  },



  onLoad(options) {

    this._shownBonusPopups = {};

    this._shownRejected = {};

    this._shownReviewNotice = {};

    this._pollTimer = null;

    this._pollBusy = false;

    this._destroyed = false;

    this._leaveTableId = '';

    this._leaveToken = '';

    const tableId = options.table_id || '';
    const qrToken = options.qr_token || '';

    this.setData({ tableId, qrToken });

    if (!tableId || !qrToken) {
      this.setData({
        loadError: '缺少桌台参数，请扫描球台二维码',
        pageReady: true,
      });
      return;
    }

    this.init();

  },



  async onShow() {

    if (this.data._initDone && this.data.tableId && this.data.qrToken && app.globalData.token) {

      const ok = await this.joinTable();

      if (ok && (!this.data.match || this.data.match.status === 'playing') && !this._pollTimer) {

        this.startPoll();

      }

    }

  },



  stopPoll() {

    if (this._pollTimer) {

      clearInterval(this._pollTimer);

      this._pollTimer = null;

    }

    if (this.data.pollTimer) {

      this.setData({ pollTimer: null });

    }

  },



  isAuthError(err) {

    const s = String(err || '');

    return s.indexOf('登录') >= 0 || s.indexOf('401') >= 0;

  },



  onHide() {

    this.stopPoll();

  },



  onUnload() {

    this._destroyed = true;

    if (this.data.cooldownTimer) clearInterval(this.data.cooldownTimer);

    this.stopPoll();

    wx.removeStorageSync('challenge_target');

    const tid = this._leaveTableId || this.data.tableId;

    const token = this._leaveToken;

    if (tid && token) {

      const prev = app.globalData.token;

      app.globalData.token = token;

      api.request(`/api/table/${tid}/leave`, 'POST', {}).catch(() => {});

      app.globalData.token = prev;

    }

  },



  mapPending(list) {

    return (list || []).map((item) => ({

      ...item,

      label: (item.claimer_name || '球友') + ' 申报' + (BONUS_LABEL[item.type] || item.type),

    }));

  },



  checkOpponentBonusPopup(pendingList) {

    if (!this.data.match || this.data.match.status !== 'playing') return;

    if (this.data.opponentBonusCard) return;

    const list = pendingList || [];

    const toShow = list.find(

      (item) => item.my_role === 'confirmer' && item.needs_opponent_popup && !this._shownBonusPopups[item.id],

    );

    if (!toShow) return;

    const typeLabel = BONUS_LABEL[toShow.type] || toShow.type;

    this.setData({

      opponentBonusCard: {

        id: toShow.id,

        claimer_name: toShow.claimer_name || '对方',

        type: toShow.type,

        typeLabel,

      },

    });

  },



  checkBonusReviewNotice(match) {

    const uid = app.globalData.user && app.globalData.user.id;

    if (!uid || !match) return;

    (match.bonuses || []).forEach((b) => {

      if (b.status !== 'pending_review' || b.user_id !== uid || this._shownReviewNotice[b.id]) return;

      this._shownReviewNotice[b.id] = true;

      wx.showToast({ title: '炸清/接清较多，已提交后台审核', icon: 'none', duration: 3000 });

    });

  },



  checkClaimerRejectedNotice(bonusPending) {

    const uid = app.globalData.user && app.globalData.user.id;

    if (!uid || !bonusPending) return;

    (bonusPending || []).forEach((p) => {

      if (p.status !== 'rejected' || p.claimer_id !== uid || this._shownRejected[p.id]) return;

      this._shownRejected[p.id] = true;

      const label = BONUS_LABEL[p.type] || p.type;

      wx.showToast({ title: `对方已拒绝您的${label}申报`, icon: 'none', duration: 2500 });

    });

  },



  closeOpponentBonusCard() {

    const card = this.data.opponentBonusCard;

    if (card && card.id) {

      this._shownBonusPopups[card.id] = true;

    }

    this.setData({ opponentBonusCard: null });

  },



  onConfirmOpponentCard() {

    const card = this.data.opponentBonusCard;

    if (!card) return;

    this._shownBonusPopups[card.id] = true;

    this.setData({ opponentBonusCard: null });

    this.doConfirmBonus(card.id);

  },



  onRejectOpponentCard() {

    const card = this.data.opponentBonusCard;

    if (!card) return;

    this._shownBonusPopups[card.id] = true;

    this.setData({ opponentBonusCard: null });

    this.doRejectBonus(card.id);

  },



  async init() {

    if (!(await this.ensureLogin())) {
      this.setData({ pageReady: true });
      return;
    }

    const ok = await this.joinTable();

    if (ok) {
      this.startPoll();
    }

    this.setData({ _initDone: true, pageReady: true });

  },



  startPoll() {

    this.stopPoll();

    this._pollTimer = setInterval(() => {

      if (this._destroyed || this._pollBusy) return;

      if (!app.globalData.token) {

        this.stopPoll();

        return;

      }

      if (!this.data.match || this.data.match.status !== 'playing') {

        this.joinTable();

      } else {

        this.refreshMatchData(this.data.match.id);

      }

    }, 3000);

    this.setData({ pollTimer: this._pollTimer });

  },



  async joinTable() {

    if (this._destroyed || this._pollBusy) return false;

    if (!this.data.tableId || !this.data.qrToken) return false;

    this._pollBusy = true;

    try {

      const table = await api.request(`/api/table/${this.data.tableId}/join`, 'POST', {

        qr_token: this.data.qrToken,

      });

      const raceTo = table.race_to || 5;

      this.setData({

        table,

        loadError: '',

        raceTo,

        racePickerIndex: raceTo === 7 ? 1 : 0,

      });

      if (table.current_match_id) {

        this._pollBusy = false;

        await this.refreshMatchData(table.current_match_id);

      } else {

        this.setData({ match: null, pendingBonuses: [] });

      }

      this._leaveTableId = this.data.tableId;

      this._leaveToken = app.globalData.token || '';

      return true;

    } catch (e) {

      this.stopPoll();

      if (!this._destroyed) {

        this.setData({ loadError: String(e) });

        wx.showToast({ title: String(e), icon: 'none' });

      }

      return false;

    } finally {

      this._pollBusy = false;

    }

  },



  async refreshMatchData(matchId) {

    if (this._destroyed || this._pollBusy) return;

    this._pollBusy = true;

    try {

      const match = await api.request(`/api/match/${matchId || this.data.match.id}`);

      const enriched = {

        ...match,

        p1: match.p1 || { nickname: '选手1' },

        p2: match.p2 || { nickname: '选手2' },

      };

      const pending = this.mapPending(match.bonus_pending_list);

      this.setData({

        match: enriched,

        pendingBonuses: pending,

        loadError: '',

      });

      this.checkOpponentBonusPopup(match.bonus_pending_list);

      this.checkClaimerRejectedNotice(match.bonus_pending);

      this.checkBonusReviewNotice(match);

      if (match.status === 'finished' || match.status === 'invalid') {

        this.goResult(match.id);

      }

    } catch (e) {

      if (this.isAuthError(e)) {

        this.stopPoll();

      }

      const m = this.data.match;

      if (m && (m.status === 'finished' || m.status === 'invalid')) {

        this.goResult(m.id);

        return;

      }

      if (!this._destroyed) {

        this.setData({ loadError: String(e) });

      }

    } finally {

      this._pollBusy = false;

    }

  },



  goResult(matchId) {

    this.stopPoll();

    wx.redirectTo({ url: `/pages/match-result/match-result?match_id=${matchId}` });

  },



  async ensureLogin() {

    if (!app.globalData.token) {

      this.setData({ loadError: '请先在首页完成微信授权登录' });

      wx.showToast({ title: '请先在首页登录', icon: 'none' });

      return false;

    }

    return true;

  },



  async onRaceChange(e) {

    const raceTo = parseInt(e.detail.value, 10) === 1 ? 7 : 5;

    this.setData({ raceTo, racePickerIndex: raceTo === 7 ? 1 : 0 });

    if (!this.data.tableId) return;

    try {

      const table = await api.request(`/api/table/${this.data.tableId}/race`, 'POST', { race_to: raceTo });

      const synced = table.race_to || raceTo;

      this.setData({

        table,

        raceTo: synced,

        racePickerIndex: synced === 7 ? 1 : 0,

      });

    } catch (err) {

      wx.showToast({ title: String(err), icon: 'none' });

    }

  },



  async startMatch() {

    if (!app.globalData.user || !app.globalData.user.id) {
      wx.showToast({ title: '请先登录', icon: 'none' });
      return;
    }

    const table = this.data.table;

    if (!table || !table.can_start) {

      wx.showToast({ title: '需两名选手均扫码到场', icon: 'none' });

      return;

    }

    const body = {

      race_to: this.data.raceTo,

      match_type: 'auto',

    };

    const challenge = wx.getStorageSync('challenge_target');

    if (challenge && table.waiting_players) {

      const other = table.waiting_players.find((p) => !p.is_me);

      if (other && other.user_id === challenge.id) {

        body.challenger_id = app.globalData.user.id;

        body.target_id = challenge.id;

        wx.removeStorageSync('challenge_target');

      }

    }

    try {

      const match = await api.request(`/api/table/${this.data.tableId}/start`, 'POST', body);

      const enriched = await api.request(`/api/match/${match.id}`);

      this._shownBonusPopups = {};

      this._shownRejected = {};

      this.setData({ match: enriched, pendingBonuses: [], opponentBonusCard: null });

      const typeTip = match.match_type === 'ranked' ? '排位赛' : '休闲局';

      const reason = match.ranked_reason ? '\n' + match.ranked_reason : '';

      wx.showModal({

        title: '对局已开始',

        content: typeTip + reason,

        showCancel: false,

      });

    } catch (e) {

      wx.removeStorageSync('challenge_target');

      wx.showToast({ title: String(e), icon: 'none' });

    }

  },



  async reportFrame(action) {

    if (this.data.cooldown > 0) {

      wx.showToast({ title: `冷却中 ${this.data.cooldown}s`, icon: 'none' });

      return;

    }

    try {

      const match = await api.request(`/api/match/${this.data.match.id}/frame`, 'POST', { action });

      this.startCooldown();

      if (match.status === 'finished' || match.status === 'invalid') {

        this.goResult(match.id);

        return;

      }

      this.setData({

        match: { ...this.data.match, ...match },

        pendingBonuses: this.mapPending(match.bonus_pending_list),

      });

    } catch (e) {

      wx.showToast({ title: String(e), icon: 'none' });

    }

  },



  startCooldown() {

    this.setData({ cooldown: 60 });

    if (this.data.cooldownTimer) clearInterval(this.data.cooldownTimer);

    const timer = setInterval(() => {

      const c = this.data.cooldown - 1;

      this.setData({ cooldown: c });

      if (c <= 0) clearInterval(timer);

    }, 1000);

    this.setData({ cooldownTimer: timer });

  },



  onWin() { this.reportFrame('win'); },

  onLose() { this.reportFrame('lose'); },



  async endEarly() {

    wx.showModal({

      title: '提前结束',

      content: '未打满局数积分将减半，确认结束？',

      success: async (r) => {

        if (!r.confirm) return;

        if (!app.globalData.user || !app.globalData.user.id) {
          wx.showToast({ title: '请先登录', icon: 'none' });
          return;
        }

        const m = this.data.match;

        const winner = m.score1 > m.score2 ? m.player1_id : (m.score2 > m.score1 ? m.player2_id : null);

        try {

          const body = { completed: false };

          if (winner) body.winner_id = winner;

          const match = await api.request(`/api/match/${m.id}/finish`, 'POST', body);

          this.goResult(match.id);

        } catch (e) {

          wx.showToast({ title: String(e), icon: 'none' });

        }

      },

    });

  },



  async requestBonus(e) {

    const type = e.currentTarget.dataset.type;

    if (!this.data.match || !this.data.match.id) {

      wx.showToast({ title: '对局未开始', icon: 'none' });

      return;

    }

    wx.showModal({

      title: '申报确认',

      content: `申报${BONUS_LABEL[type]}？将通知对方手机弹窗确认，双方各确认一次后加分`,

      success: async (res) => {

        if (!res.confirm) return;

        try {

          const data = await api.request(

            `/api/match/${this.data.match.id}/bonus/request`,

            'POST',

            { type },

          );

          wx.showToast({ title: '已通知对方确认', icon: 'none' });

          this.setData({ pendingBonuses: this.mapPending(data.pending) });

          this.refreshMatchData(this.data.match.id);

        } catch (err) {

          wx.showToast({ title: String(err), icon: 'none' });

        }

      },

    });

  },



  async confirmBonus(e) {

    await this.doConfirmBonus(e.currentTarget.dataset.id);

  },



  async doConfirmBonus(bonusId) {

    if (!bonusId || !this.data.match) return;

    try {

      const data = await api.request(`/api/match/${this.data.match.id}/bonus/confirm`, 'POST', {

        bonus_id: bonusId,

      });

      wx.showToast({

        title: data.applied ? '双方已确认，加分成功' : '已确认，等待申报方确认',

        icon: 'none',

      });

      this.setData({ pendingBonuses: this.mapPending(data.pending) });

      this.refreshMatchData(this.data.match.id);

    } catch (err) {

      wx.showToast({ title: String(err), icon: 'none' });

    }

  },



  async doRejectBonus(bonusId) {

    if (!bonusId || !this.data.match) return;

    try {

      const data = await api.request(`/api/match/${this.data.match.id}/bonus/reject`, 'POST', {

        bonus_id: bonusId,

      });

      wx.showToast({ title: '已拒绝该申报', icon: 'none' });

      this.setData({ pendingBonuses: this.mapPending(data.pending) });

      this.refreshMatchData(this.data.match.id);

    } catch (err) {

      wx.showToast({ title: String(err), icon: 'none' });

    }

  },



  refreshMatch() {

    if (this.data.match) {

      this.refreshMatchData(this.data.match.id);

    } else {

      this.joinTable();

    }

  },



  noop() {},

});

