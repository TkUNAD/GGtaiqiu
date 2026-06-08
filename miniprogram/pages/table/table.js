const api = require('../../utils/api');
const { parseTableScanResult } = require('../../utils/tableQr');
const { getVenueId } = require('../../utils/venueStore');
const { getTierStyle } = require('../../utils/tierIcons');
const { DEFAULT_AVATAR, resolveDisplayAvatar } = require('../../utils/avatar');

const app = getApp();

const BONUS_LABEL = { break_run: '炸清+20', clearance: '接清+15' };
const ACTION_COOLDOWN_SEC = 20;
/** 切到微信聊天等后台：仍占坑时长（毫秒） */
const LOBBY_BACKGROUND_LEAVE_MS = 60000;
const RACE_OPTIONS = [5, 7, 9, 11, 13];
const RACE_LABELS = RACE_OPTIONS.map((n) => `抢${n}`);

function raceToPickerIndex(raceTo) {
  const n = normalizeRaceTo(raceTo);
  const idx = RACE_OPTIONS.indexOf(n);
  return idx >= 0 ? idx : 0;
}
function normalizeRaceTo(v) {
  const n = parseInt(v, 10);
  return RACE_OPTIONS.indexOf(n) >= 0 ? n : 5;
}

function decorateLobbyPlayer(p, fallbackName) {
  if (!p || !p.user_id) {
    return {
      nickname: fallbackName,
      avatar: DEFAULT_AVATAR,
      tierImage: getTierStyle(1).tierImage,
      tierName: '等待选手',
    };
  }
  const tier = getTierStyle(p.tier_index || 1);
  return {
    nickname: (p.nickname || fallbackName) + (p.is_me ? '（我）' : ''),
    avatar: resolveDisplayAvatar(p.avatar),
    tierImage: tier.tierImage,
    tierName: p.tier_name ? `${p.tier_name} ${p.star || 1}星` : tier.tierName,
  };
}

function isMatchEnded(status) {
  return status === 'finished' || status === 'invalid' || status === 'pending_review';
}

function decorateMatchPlayer(u, fallback) {
  const raw = u || {};
  const tier = getTierStyle(raw.tier_index || 1);
  const tierLabel = raw.tier_name
    ? `${raw.tier_name}${raw.star ? ` ${raw.star}星` : ''}`
    : tier.tierName;
  return {
    ...raw,
    nickname: raw.nickname || fallback,
    avatarUrl: resolveDisplayAvatar(raw.avatar),
    tierImage: tier.tierImage,
    tierName: tierLabel,
  };
}



Page({

  data: {

    tableId: '',

    qrToken: '',

    table: null,

    match: null,

    raceTo: 5,
    raceLabels: RACE_LABELS,
    racePickerIndex: 0,
    racePickerOpen: false,
    lobbyP1: decorateLobbyPlayer(null, '选手1'),
    lobbyP2: decorateLobbyPlayer(null, '选手2'),
    matchType: 'casual',

    cooldown: 0,

    cooldownTimer: null,

    pendingBonuses: [],

    opponentBonusCard: null,

    loadError: '',
    pageReady: false,
    _initDone: false,
    idleUi: { active: false },
    idleCountdownTimer: null,
    expectedVenueId: '',

  },



  onLoad(options) {

    this._shownBonusPopups = {};

    this._shownRejected = {};

    this._shownReviewNotice = {};

    this._pollTimer = null;

    this._pollBusy = false;

    this._destroyed = false;

    this._leaveTableId = '';

    this._lobbyLeaveTimer = null;

    let tableId = options.table_id || '';
    let qrToken = options.qr_token || '';
    if (options.scene) {
      const parsed = parseTableScanResult(decodeURIComponent(options.scene));
      if (parsed) {
        tableId = parsed.tableId;
        qrToken = parsed.qrToken;
      }
    }
    const expectedVenueId = options.venue_id || getVenueId();

    this.setData({ tableId, qrToken, expectedVenueId });

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

    this._cancelLobbyLeaveTimer();

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

  },



  isAuthError(err) {

    const s = String(err || '');

    return s.indexOf('登录') >= 0 || s.indexOf('401') >= 0;

  },



  isInLobby() {
    const playing = this.data.match && this.data.match.status === 'playing';
    return !playing && this.data.tableId && this.data.table && this.data.table.i_am_waiting;
  },

  _cancelLobbyLeaveTimer() {
    if (this._lobbyLeaveTimer) {
      clearTimeout(this._lobbyLeaveTimer);
      this._lobbyLeaveTimer = null;
    }
  },

  leaveLobbySilent() {
    if (!this.isInLobby()) return Promise.resolve();
    const tid = this._leaveTableId || this.data.tableId;
    const token = app.globalData.accessToken || app.globalData.token || wx.getStorageSync('access_token');
    if (!tid || !token) return Promise.resolve();
    return api
      .request(`/api/table/${encodeURIComponent(tid)}/leave`, 'POST', {})
      .catch(() => {});
  },

  /** 切到后台：60 秒内仍占坑；超时或真正关闭后再离场 */
  onHide() {
    this.stopPoll();
    this._cancelLobbyLeaveTimer();
    if (!this.isInLobby()) return;
    this._lobbyLeaveTimer = setTimeout(() => {
      this._lobbyLeaveTimer = null;
      this.leaveLobbySilent();
    }, LOBBY_BACKGROUND_LEAVE_MS);
  },



  syncIdleCountdown(idleUi) {

    if (this.data.idleCountdownTimer) {

      clearInterval(this.data.idleCountdownTimer);

      this.setData({ idleCountdownTimer: null });

    }

    if (!idleUi || !idleUi.active) return;

    const timer = setInterval(() => {

      const ui = { ...this.data.idleUi };

      if (!ui.active) return;

      if (ui.seconds_left > 0) ui.seconds_left -= 1;

      if (ui.end_seconds_left > 0) ui.end_seconds_left -= 1;

      this.setData({ idleUi: ui });

    }, 1000);

    this.setData({ idleCountdownTimer: timer });

  },

  onUnload() {
    this._destroyed = true;
    this._cancelLobbyLeaveTimer();
    if (this.data.cooldownTimer) clearInterval(this.data.cooldownTimer);
    if (this.data.idleCountdownTimer) clearInterval(this.data.idleCountdownTimer);

    this.stopPoll();

    wx.removeStorageSync('challenge_target');

    this.leaveLobbySilent();
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

      wx.showToast({
        title: '炸清/接清待审核，未加分未计胜局，可继续对战',
        icon: 'none',
        duration: 3000,
      });

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

    const pollOnce = async () => {
      if (this._destroyed) return;
      if (this._pollBusy) {
        this._pollRetry = true;
        return;
      }
      if (!app.globalData.token) {
        return;
      }
      const playing =
        (this.data.match && this.data.match.status === 'playing') ||
        (this.data.table && this.data.table.current_match_id);
      if (!playing) {
        await this.joinTable();
      } else {
        const mid =
          (this.data.match && this.data.match.id) ||
          (this.data.table && this.data.table.current_match_id);
        if (mid) await this.refreshMatchData(mid);
      }
    };

    pollOnce();
    this._pollTimer = setInterval(() => {
      pollOnce();
    }, 2000);

  },



  async joinTable() {

    if (this._destroyed || this._pollBusy) return false;

    if (!this.data.tableId || !this.data.qrToken) return false;

    this._pollBusy = true;

    try {

      const venueId = this.data.expectedVenueId || getVenueId();
      const table = await api.request(`/api/table/${this.data.tableId}/join`, 'POST', {
        qr_token: this.data.qrToken,
        venue_id: venueId,
      });

      const raceTo = normalizeRaceTo(table.race_to || 5);

      this.setData({
        table,
        loadError: '',
        raceTo,
        racePickerIndex: raceToPickerIndex(raceTo),
        ...this.buildLobbyPlayers(table),
      });

      if (table.current_match_id) {

        const wasPlaying = this.data.match && this.data.match.status === 'playing';

        await this.refreshMatchData(table.current_match_id, true);

        if (!wasPlaying && this.data.match && this.data.match.status === 'playing') {

          wx.showToast({ title: '对局已开始', icon: 'success' });

        }

      } else {

        this.setData({ match: null, pendingBonuses: [] });

      }

      this._leaveTableId = this.data.tableId;


      return true;

    } catch (e) {
      if (this.isAuthError(e)) {
        const refreshed = await api.tryRefreshToken().catch(() => false);
        if (!refreshed) {
          this.stopPoll();
        }
      }
      if (!this._destroyed) {
        this.setData({ loadError: String(e) });
        if (!this.isAuthError(e)) {
          wx.showToast({ title: String(e), icon: 'none' });
        }
      }
      return false;
    } finally {
      this._pollBusy = false;
      if (this._pollRetry && !this._destroyed) {
        this._pollRetry = false;
        if (this.data.match && this.data.match.status === 'playing') {
          this.refreshMatchData(this.data.match.id);
        } else if (this.data.tableId) {
          this.joinTable();
        }
      }

    }

  },



  async refreshMatchData(matchId, fromJoin) {

    if (this._destroyed) return;

    if (!fromJoin && this._pollBusy) {
      this._pollRetry = true;
      return;
    }

    this._pollBusy = true;

    try {

      const id =
        matchId ||
        (this.data.table && this.data.table.current_match_id) ||
        (this.data.match && this.data.match.id);
      if (!id) return;

      const shouldSync =
        (this.data.table && this.data.table.current_match_id) ||
        (this.data.match && this.data.match.status === 'playing');

      const match = shouldSync
        ? await api.request(`/api/match/${id}/sync`, 'POST', {})
        : await api.request(`/api/match/${id}`);

      const enriched = {
        ...match,
        p1: decorateMatchPlayer(match.p1, '选手1'),
        p2: decorateMatchPlayer(match.p2, '选手2'),
      };

      const pending = this.mapPending(match.bonus_pending_list);

      this.setData({

        match: enriched,

        pendingBonuses: pending,

        loadError: '',

        idleUi: match.idle_ui || { active: false },

      });
      this.syncIdleCountdown(match.idle_ui);

      this.checkOpponentBonusPopup(match.bonus_pending_list);

      this.checkClaimerRejectedNotice(match.bonus_pending);

      this.checkBonusReviewNotice(match);

      this.syncCooldownFromMatch(enriched);

      if (isMatchEnded(match.status)) {

        this.goResult(match.id);

        return;

      }

    } catch (e) {
      if (this.isAuthError(e)) {
        const refreshed = await api.tryRefreshToken().catch(() => false);
        if (!refreshed) {
          this.stopPoll();
        }
      }
      const m = this.data.match;

      if (m && isMatchEnded(m.status)) {

        this.goResult(m.id);

        return;

      }

      if (!this._destroyed) {

        this.setData({ loadError: String(e) });

      }

    } finally {

      this._pollBusy = false;

      if (this._pollRetry) {
        this._pollRetry = false;
        const playing = this.data.match && this.data.match.status === 'playing';
        if (playing) {
          this.refreshMatchData(this.data.match.id);
        } else if (this.data.tableId) {
          this.joinTable();
        }
      }

    }

  },



  goResult(matchId) {

    if (this._resultNavigated) return;

    this._resultNavigated = true;

    this.stopPoll();

    wx.redirectTo({ url: `/pages/match-result/match-result?match_id=${matchId}` });

  },



  async ensureLogin() {

    const token = app.globalData.accessToken || app.globalData.token || wx.getStorageSync('access_token');

    if (token) {

      app.globalData.token = token;

      app.globalData.accessToken = token;

      return true;

    }

    try {

      await api.login();

      return true;

    } catch (e) {

      this.setData({ loadError: '请先在「我的」完成微信授权登录' });

      wx.showToast({ title: String(e), icon: 'none' });

      setTimeout(() => wx.switchTab({ url: '/pages/index/index' }), 1500);

      return false;

    }

  },



  buildLobbyPlayers(table) {
    const waiting = (table && table.waiting_players) || [];
    return {
      lobbyP1: decorateLobbyPlayer(waiting[0], '选手1'),
      lobbyP2: decorateLobbyPlayer(waiting[1], '选手2'),
    };
  },

  openRacePicker() {
    this.setData({ racePickerOpen: true });
  },

  closeRacePicker() {
    this.setData({ racePickerOpen: false });
  },

  onRaceOptionTap(e) {
    const idx = parseInt(e.currentTarget.dataset.index, 10);
    this.closeRacePicker();
    this.applyRaceSelection(idx);
  },

  async applyRaceSelection(idx) {
    const raceTo = RACE_OPTIONS[idx] || 5;
    if (raceTo === this.data.raceTo) return;
    const prevRace = this.data.raceTo;
    const prevIdx = this.data.racePickerIndex;
    this.setData({ raceTo, racePickerIndex: idx });
    if (!this.data.tableId) return;
    try {
      const table = await api.request(`/api/table/${this.data.tableId}/race`, 'POST', { race_to: raceTo });
      const synced = normalizeRaceTo(table.race_to || raceTo);
      this.setData({
        table,
        raceTo: synced,
        racePickerIndex: raceToPickerIndex(synced),
        ...this.buildLobbyPlayers(table),
      });
    } catch (err) {
      wx.showToast({ title: String(err), icon: 'none' });
      this.setData({
        raceTo: prevRace,
        racePickerIndex: prevIdx,
      });
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
      venue_id: this.data.expectedVenueId || getVenueId(),
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

      const table = this.data.table || {};

      this.setData({
        match: {
          ...enriched,
          p1: decorateMatchPlayer(enriched.p1, '选手1'),
          p2: decorateMatchPlayer(enriched.p2, '选手2'),
        },
        pendingBonuses: [],
        opponentBonusCard: null,
        table: {
          ...table,
          current_match_id: match.id,
          can_start: false,
          waiting_count: 0,
          waiting_players: [],
          players_ready: false,
        },
      });

      if (!this._pollTimer) this.startPoll();

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



  isCooldownActive() {
    return this.data.cooldown > 0;
  },

  clearCooldown() {
    if (this.data.cooldownTimer) {
      clearInterval(this.data.cooldownTimer);
      this.setData({ cooldownTimer: null });
    }
    this.setData({ cooldown: 0 });
  },

  syncCooldownFromMatch(match) {
    const serverSec = (match && match.action_cooldown_remaining) || 0;
    if (serverSec > 0) {
      this.startCooldown(serverSec);
    } else {
      this.clearCooldown();
    }
  },

  applyCooldownFromResponse(payload) {
    const sec = (payload && payload.action_cooldown_remaining) || 0;
    if (sec > 0) {
      this.startCooldown(sec);
    }
  },

  async reportFrame(action) {
    if (this.isCooldownActive()) {
      wx.showToast({ title: `请等待 ${this.data.cooldown} 秒后再操作`, icon: 'none' });
      return;
    }
    try {
      const match = await api.request(`/api/match/${this.data.match.id}/frame`, 'POST', { action });
      this.applyCooldownFromResponse(match);
      if (isMatchEnded(match.status)) {
        this.goResult(match.id);
        return;
      }
      const merged = {
        ...this.data.match,
        ...match,
        p1: decorateMatchPlayer(match.p1 || this.data.match.p1, '选手1'),
        p2: decorateMatchPlayer(match.p2 || this.data.match.p2, '选手2'),
      };
      this.setData({
        match: merged,
        pendingBonuses: this.mapPending(match.bonus_pending_list),
      });
    } catch (e) {
      wx.showToast({ title: String(e), icon: 'none' });
    }
  },



  startCooldown(seconds) {
    const sec = seconds > 0 ? seconds : ACTION_COOLDOWN_SEC;
    if (this.data.cooldownTimer) clearInterval(this.data.cooldownTimer);
    this.setData({ cooldown: sec });
    const timer = setInterval(() => {
      const c = this.data.cooldown - 1;
      this.setData({ cooldown: c });
      if (c <= 0) {
        clearInterval(timer);
        this.setData({ cooldownTimer: null });
      }
    }, 1000);
    this.setData({ cooldownTimer: timer });
  },



  onWin() { this.reportFrame('win'); },

  onLose() { this.reportFrame('lose'); },

  onPlayAvatarError(e) {
    const side = e.currentTarget.dataset.side;
    if (!side || !this.data.match) return;
    const key = `match.${side}.avatarUrl`;
    this.setData({ [key]: DEFAULT_AVATAR });
  },

  onLobbyAvatarError(e) {
    const slot = e.currentTarget.dataset.slot;
    if (!slot) return;
    this.setData({ [`${slot}.avatar`]: DEFAULT_AVATAR });
  },

  async onIdleContinue() {
    if (!this.data.match || !this.data.match.id) return;
    if (!this.data.idleUi.need_my_continue) return;
    try {
      const match = await api.request(`/api/match/${this.data.match.id}/idle/continue`, 'POST', {});
      if (isMatchEnded(match.status)) {
        this.goResult(match.id);
        return;
      }
      await this.refreshMatchData(match.id);
      if (match.idle_ui && match.idle_ui.both_continue_ready) {
        wx.showToast({ title: '双方已确认，比赛继续', icon: 'none' });
      }
    } catch (e) {
      wx.showToast({ title: String(e), icon: 'none' });
    }
  },

  async onIdleEnd() {
    if (!this.data.match || !this.data.match.id) return;
    try {
      const match = await api.request(`/api/match/${this.data.match.id}/idle/end`, 'POST', {});
      if (isMatchEnded(match.status)) {
        this.goResult(match.id);
        return;
      }
      await this.refreshMatchData(match.id);
      wx.showToast({ title: '已通知对方', icon: 'none' });
    } catch (e) {
      wx.showToast({ title: String(e), icon: 'none' });
    }
  },

  async onIdleAgreeEnd() {
    await this._idleEndResponse(true);
  },

  async onIdleRejectEnd() {
    await this._idleEndResponse(false);
  },

  async _idleEndResponse(agree) {
    if (!this.data.match || !this.data.match.id) return;
    try {
      const match = await api.request(
        `/api/match/${this.data.match.id}/idle/end-response`,
        'POST',
        { agree },
      );
      if (isMatchEnded(match.status)) {
        this.goResult(match.id);
        return;
      }
      await this.refreshMatchData(match.id);
      wx.showToast({
        title: agree ? '已同意结束' : '已拒绝，比赛继续',
        icon: 'none',
      });
    } catch (e) {
      wx.showToast({ title: String(e), icon: 'none' });
    }
  },



  async endEarly() {

    wx.showModal({

      title: '提前结束',

      content: '未打满局数积分将减半，确认结束？',

      success: (r) => {

        if (!r.confirm) return;

        if (!app.globalData.user || !app.globalData.user.id) {
          wx.showToast({ title: '请先登录', icon: 'none' });
          return;
        }

        const m = this.data.match;

        const winner = m.score1 > m.score2 ? m.player1_id : (m.score2 > m.score1 ? m.player2_id : null);

        const body = { completed: false };

        if (winner) body.winner_id = winner;

        api.request(`/api/match/${m.id}/finish`, 'POST', body)
          .then((match) => {
            this.goResult(match.id);
          })
          .catch((e) => {
            wx.showToast({ title: String(e), icon: 'none' });
          });

      },

    });

  },



  async requestBonus(e) {

    const type = e.currentTarget.dataset.type;

    if (!this.data.match || !this.data.match.id) {

      wx.showToast({ title: '对局未开始', icon: 'none' });

      return;

    }

    if (this.isCooldownActive()) {

      wx.showToast({ title: `请等待 ${this.data.cooldown} 秒后再申报`, icon: 'none' });

      return;

    }

    wx.showModal({

      title: '申报确认',

      content: `申报${BONUS_LABEL[type]}？将通知对方确认，对方同意后即可加分并为您胜1局`,

      success: (res) => {

        if (!res.confirm) return;

        api.request(

          `/api/match/${this.data.match.id}/bonus/request`,

          'POST',

          { type },

        )
          .then((data) => {
            wx.showToast({ title: '已通知对方确认', icon: 'none' });
            if (data.action_cooldown_remaining > 0) {
              this.startCooldown(data.action_cooldown_remaining);
            } else {
              this.startCooldown(ACTION_COOLDOWN_SEC);
            }
            this.setData({ pendingBonuses: this.mapPending(data.pending) });
            this.refreshMatchData(this.data.match.id);
          })
          .catch((err) => {
            wx.showToast({ title: String(err), icon: 'none' });
          });

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

      let tip = '已同意，申报生效';
      if (data.pending_review) {
        tip = '已同意，待后台审核（未加分、未计胜局），可继续对战';
      } else if (data.frame_awarded) {
        tip = data.match_finished ? '已同意：对方加分胜局，对局已结束' : '已同意：对方加分并胜1局';
      } else if (data.applied) {
        tip = '已同意，加分成功';
      }
      wx.showToast({ title: tip, icon: 'none', duration: data.match_finished ? 2500 : 1500 });

      if (data.match && data.match.action_cooldown_remaining > 0) {
        this.startCooldown(data.match.action_cooldown_remaining);
      } else if (!data.match_finished) {
        this.startCooldown(ACTION_COOLDOWN_SEC);
      }

      this.setData({ pendingBonuses: this.mapPending(data.pending) });

      if (data.match_finished || (data.match && isMatchEnded(data.match.status))) {
        this.stopPoll();
        this.goResult(this.data.match.id);
        return;
      }

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

