const api = require('../../utils/api');
const { getVenueId } = require('../../utils/venueStore');
const { decorateList, padLeaderboardTop } = require('../../utils/rank');
const { getTierStyle } = require('../../utils/tierIcons');

const RANK_REFRESH_MS = 12000;
const TOP_PAD = 10;

const CLUB_BOARD_DESC = {
  week: '按本周积分增加排名（仅本俱乐部选手，不含段位）',
  month: '按本月积分增加排名（仅本俱乐部选手，不含段位）',
  total: '按当前总积分排名（仅本俱乐部选手）',
};

Page({
  data: {
    tab: 'club',
    clubBoard: 'total',
    clubBoardDesc: CLUB_BOARD_DESC.total,
    list: [],
    loading: true,
    playerDetail: null,
  },

  onShow() {
    this.load();
    this.startRankRefresh();
  },

  onHide() {
    this.stopRankRefresh();
  },

  startRankRefresh() {
    this.stopRankRefresh();
    this._rankRefreshTimer = setInterval(() => {
      this.load(true);
    }, RANK_REFRESH_MS);
  },

  stopRankRefresh() {
    if (this._rankRefreshTimer) {
      clearInterval(this._rankRefreshTimer);
      this._rankRefreshTimer = null;
    }
  },

  switchTab(e) {
    const tab = e.currentTarget.dataset.tab;
    if (tab === this.data.tab) return;
    this.setData({ tab });
    this.load();
  },

  switchClubBoard(e) {
    const board = e.currentTarget.dataset.board;
    if (!board || board === this.data.clubBoard) return;
    this.setData({
      clubBoard: board,
      clubBoardDesc: CLUB_BOARD_DESC[board] || CLUB_BOARD_DESC.total,
    });
    this.load();
  },

  load(silent) {
    const reqId = (this._loadSeq || 0) + 1;
    this._loadSeq = reqId;
    if (!silent) this.setData({ loading: true });
    const isClub = this.data.tab === 'club';
    const tab = this.data.tab;
    const clubBoard = this.data.clubBoard || 'total';
    let url;
    if (isClub) {
      url = `/api/rank/club?limit=50&venue_id=${encodeURIComponent(getVenueId())}&board=${clubBoard}`;
    } else {
      url = '/api/rank/global?limit=50';
    }
    const rankKey = isClub ? 'club_rank' : 'rank';
    return api
      .request(url)
      .then((list) => {
        if (this._loadSeq !== reqId) return;
        if (this.data.tab !== tab) return;
        if (isClub && this.data.clubBoard !== clubBoard) return;
        const decorated = decorateList(list);
        const padded = padLeaderboardTop(decorated, TOP_PAD, rankKey);
        this.setData({ list: padded, loading: false });
      })
      .catch((e) => {
        if (this._loadSeq !== reqId) return;
        if (!silent) wx.showToast({ title: e, icon: 'none' });
        this.setData({ loading: false });
      });
  },

  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh());
  },

  showPlayer(e) {
    const id = e.currentTarget.dataset.id;
    if (!id) return;
    api.request(`/api/rank/player/${id}`)
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
});
