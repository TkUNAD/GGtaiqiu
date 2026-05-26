const api = require('../../utils/api');
const app = getApp();

const FX_DURATION = 4000;

Page({
  data: {
    summary: null,
    matchId: '',
    loadError: '',
    fxKind: '',
    fxOldTier: 1,
    fxNewTier: 1,
    fxPlaying: false,
    fxSeq: 0,
  },

  onLoad(options) {
    this.setData({ matchId: options.match_id || '' });
    this.load();
  },

  onUnload() {
    this._clearFxTimers();
  },

  _clearFxTimers() {
    if (this._fxTimer) {
      clearTimeout(this._fxTimer);
      this._fxTimer = null;
    }
  },

  async _ensureUser() {
    if (app.globalData.user && app.globalData.user.id) {
      return app.globalData.user;
    }
    try {
      const profile = await api.request('/api/user/profile');
      const u = { ...profile.user, tier: profile.tier, rank: profile.rank };
      app.setUser(u, app.globalData.token || app.globalData.accessToken);
      return u;
    } catch (e) {
      return null;
    }
  },

  _getMyPlayer(summary) {
    const user = app.globalData.user;
    if (!user || !user.id || !summary) return null;
    const id = user.id;
    if (summary.player1 && summary.player1.id === id) return summary.player1;
    if (summary.player2 && summary.player2.id === id) return summary.player2;
    return null;
  },

  _outcomeFromScore(summary, me) {
    if (!me || !summary) return 'lose';
    if (me.is_winner) return 'win';
    const s1 = summary.score1 || 0;
    const s2 = summary.score2 || 0;
    if (s1 === s2) return 'draw';
    const p1 = summary.player1 && summary.player1.id;
    const p2 = summary.player2 && summary.player2.id;
    if (me.id === p1) return s1 > s2 ? 'win' : 'lose';
    if (me.id === p2) return s2 > s1 ? 'win' : 'lose';
    return 'lose';
  },

  _buildFxQueue(me, summary) {
    if (!me || !summary) return [];
    const queue = [];
    const skipTier = summary.status === 'invalid' || !!summary.invalid_reason;
    if (!skipTier && me.tier_promoted) {
      queue.push({
        type: 'tierUp',
        oldTier: me.tier_before_index || 1,
        newTier: me.tier_index || 1,
      });
    }
    const s1 = summary.score1 || 0;
    const s2 = summary.score2 || 0;
    const isDraw = summary.is_draw
      || (s1 === s2 && (!summary.winner_id || summary.status === 'invalid'))
      || this._outcomeFromScore(summary, me) === 'draw';
    const outcome = isDraw ? 'draw' : this._outcomeFromScore(summary, me);
    if (outcome === 'draw') {
      queue.push({ type: 'draw' });
    } else if (outcome === 'win') {
      queue.push({ type: 'win' });
    } else {
      queue.push({ type: 'lose' });
    }
    return queue;
  },

  _playFxQueue(queue, index) {
    this._clearFxTimers();
    this._fxQueue = queue;
    this._fxIndex = index;
    if (!queue || index >= queue.length) {
      this.setData({ fxKind: '', fxPlaying: false, fxSeq: 0 });
      this._fxQueue = null;
      this._fxIndex = null;
      return;
    }
    const item = queue[index];
    this.setData({
      fxPlaying: true,
      fxKind: item.type,
      fxOldTier: item.oldTier || 1,
      fxNewTier: item.newTier || 1,
      fxSeq: (this.data.fxSeq || 0) + 1,
    });
  },

  async _startEffects(summary) {
    await this._ensureUser();
    const me = this._getMyPlayer(summary);
    const queue = this._buildFxQueue(me, summary);
    if (queue.length) {
      this._playFxQueue(queue, 0);
    } else {
      this.setData({ fxPlaying: false, fxKind: '' });
    }
  },

  async load() {
    if (!this.data.matchId) {
      this.setData({ loadError: '缺少对局编号' });
      return;
    }
    try {
      await this._ensureUser();
      const summary = await api.request(`/api/match/${this.data.matchId}/summary`);
      this.setData({ summary, loadError: '' });
      this._startEffects(summary);
      const token = app.globalData.accessToken || app.globalData.token;
      if (token) {
        api.request('/api/user/profile').then((profile) => {
          const u = { ...profile.user, tier: profile.tier, rank: profile.rank };
          app.setUser(u, app.globalData.token);
        }).catch(() => {});
      }
    } catch (e) {
      this.setData({ loadError: String(e) });
      wx.showToast({ title: String(e), icon: 'none' });
    }
  },

  onFxDone() {
    if (!this._fxQueue || this._fxIndex == null || this._fxAdvancing) return;
    this._fxAdvancing = true;
    this.setData({ fxKind: '' });
    const next = this._fxIndex + 1;
    setTimeout(() => {
      this._fxAdvancing = false;
      this._playFxQueue(this._fxQueue, next);
    }, 100);
  },

  onConfirm() {
    this._clearFxTimers();
    wx.switchTab({ url: '/pages/index/index' });
  },
});
