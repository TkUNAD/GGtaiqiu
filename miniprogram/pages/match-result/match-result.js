const api = require('../../utils/api');
const app = getApp();

const FX_DURATION = 4000;

Page({
  data: {
    summary: null,
    matchId: '',
    loadError: '',
    fxType: '',
    fxOldTier: 1,
    fxNewTier: 1,
    fxPlaying: false,
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

  _getMyPlayer(summary) {
    const user = app.globalData.user;
    if (!user || !user.id || !summary) return null;
    const id = user.id;
    if (summary.player1 && summary.player1.id === id) return summary.player1;
    if (summary.player2 && summary.player2.id === id) return summary.player2;
    return null;
  },

  _buildFxQueue(me, summary) {
    if (!me || summary.status === 'invalid' || summary.invalid_reason) return [];
    const queue = [];
    if (me.tier_promoted) {
      queue.push({
        type: 'tierUp',
        oldTier: me.tier_before_index || 1,
        newTier: me.tier_index || 1,
      });
    }
    const isDraw = summary.is_draw
      || (!summary.winner_id && summary.status === 'finished'
        && summary.score1 === summary.score2);
    if (isDraw) queue.push({ type: 'draw' });
    else if (me.is_winner) queue.push({ type: 'win' });
    else queue.push({ type: 'lose' });
    return queue;
  },

  _playFxQueue(queue, index) {
    this._clearFxTimers();
    this._fxQueue = queue;
    this._fxIndex = index;
    if (!queue || index >= queue.length) {
      this.setData({ fxType: '', fxPlaying: false });
      this._fxQueue = null;
      this._fxIndex = null;
      return;
    }
    const item = queue[index];
    this.setData({
      fxPlaying: true,
      fxType: item.type,
      fxOldTier: item.oldTier || 1,
      fxNewTier: item.newTier || 1,
    });
    this._fxTimer = setTimeout(() => {
      this.setData({ fxType: '' });
      this._playFxQueue(queue, index + 1);
    }, FX_DURATION + 150);
  },

  _startEffects(summary) {
    const me = this._getMyPlayer(summary);
    const queue = this._buildFxQueue(me, summary);
    if (queue.length) this._playFxQueue(queue, 0);
  },

  async load() {
    if (!this.data.matchId) {
      this.setData({ loadError: '缺少对局编号' });
      return;
    }
    try {
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
    if (this._fxQueue && this._fxIndex != null) {
      this._playFxQueue(this._fxQueue, this._fxIndex + 1);
    }
  },

  onClose() {
    this._clearFxTimers();
    wx.switchTab({ url: '/pages/profile/profile' });
  },
});
