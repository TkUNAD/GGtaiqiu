const api = require('../../utils/api');
const app = getApp();

const EXCHANGE_STATUS_LABEL = {
  pending: '待审核',
  approved: '已通过',
  rejected: '已拒绝',
};

Page({
  data: {
    products: [],
    exchanges: [],
    exchangeRules: null,
    tab: 'shop',
    loggedIn: false,
    exchanging: false,
  },

  onShow() {
    const pendingTab = wx.getStorageSync('shop_tab');
    if (pendingTab === 'records') {
      wx.removeStorageSync('shop_tab');
      this.setData({ tab: 'records' });
    }
    this.load();
  },

  async load() {
    const loggedIn = !!(app.globalData && app.globalData.token);
    this.setData({ loggedIn });
    try {
      const shopData = await api.request('/api/shop/products');
      const products = Array.isArray(shopData) ? shopData : (shopData.products || []);
      const exchangeRules = !Array.isArray(shopData) ? (shopData.rules || null) : null;
      this.setData({ products, exchangeRules });
      if (loggedIn) {
        const raw = await api.request('/api/shop/my-exchanges');
        const exchanges = (raw || []).map((item) => ({
          ...item,
          statusLabel: EXCHANGE_STATUS_LABEL[item.status] || item.status,
        }));
        this.setData({ exchanges });
      } else {
        this.setData({ exchanges: [] });
      }
    } catch (e) {
      wx.showToast({ title: e, icon: 'none' });
    }
  },

  switchTab(e) {
    this.setData({ tab: e.currentTarget.dataset.tab });
  },

  goLogin() {
    wx.switchTab({ url: '/pages/index/index' });
  },

  exchange(e) {
    if (this.data.exchanging) return;
    if (!app.globalData.token) {
      wx.showToast({ title: '请先登录后再兑换', icon: 'none' });
      return;
    }
    const rules = this.data.exchangeRules;
    if (rules && !rules.can_exchange) {
      let tip = rules.rule_text || '当前不可兑换';
      if (rules.user_score < rules.min_score) {
        tip = `积分需达到${rules.min_score}分方可兑换（当前${rules.user_score}分）`;
      } else if (rules.exchanges_today >= rules.daily_limit) {
        tip = `今日兑换次数已达上限（每日${rules.daily_limit}次）`;
      }
      wx.showToast({ title: tip, icon: 'none', duration: 2500 });
      return;
    }
    const id = e.currentTarget.dataset.id;
    const name = e.currentTarget.dataset.name;
    wx.showModal({
      title: '确认兑换',
      content: `兑换 ${name}？`,
      success: (r) => {
        if (!r.confirm) return;
        this.setData({ exchanging: true });
        api.request('/api/shop/exchange', 'POST', { product_id: id })
          .then(() => {
            wx.showToast({ title: '兑换成功，待审核发放' });
            return this.load();
          })
          .catch((err) => {
            wx.showToast({ title: err, icon: 'none' });
          })
          .finally(() => {
            this.setData({ exchanging: false });
          });
      },
    });
  },
});
