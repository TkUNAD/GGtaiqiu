const adminApi = require('./adminApi');

function fetchMembershipSummary() {
  return adminApi.adminRequest('/api/admin/membership/summary');
}

function openRenewPicker(plans, onSuccess) {
  const list = plans || [];
  if (!list.length) {
    wx.showToast({ title: '暂无续费套餐', icon: 'none' });
    return;
  }
  const labels = list.map((p) => `${p.label} ¥${p.price_yuan}`);
  wx.showActionSheet({
    itemList: labels,
    success: (res) => {
      const plan = list[res.tapIndex];
      if (plan) {
        payMembership(plan.id).then(() => {
          if (typeof onSuccess === 'function') onSuccess();
        });
      }
    },
  });
}

function payMembership(planId) {
  return new Promise(async (resolve, reject) => {
    wx.showLoading({ title: '拉起支付...', mask: true });
    try {
      const res = await adminApi.adminRequest('/api/mp-admin/membership/orders', 'POST', {
        plan_id: planId,
        pay_channel: 'wechat_jsapi',
      });
      wx.hideLoading();
      if (res.payment && res.payment.dev_mode) {
        await adminApi.adminRequest(
          `/api/admin/membership/orders/${encodeURIComponent(res.order.id)}/mock-pay`,
          'POST',
        );
        wx.showToast({ title: '续费成功', icon: 'success' });
        resolve(res);
        return;
      }
      const wxPay = res.payment && res.payment.wechat;
      if (!wxPay) {
        wx.showToast({ title: '支付未配置或参数失败', icon: 'none' });
        reject(new Error('支付参数失败'));
        return;
      }
      await new Promise((resPay, rejPay) => {
        wx.requestPayment({
          timeStamp: wxPay.timeStamp,
          nonceStr: wxPay.nonceStr,
          package: wxPay.package,
          signType: wxPay.signType || 'MD5',
          paySign: wxPay.paySign,
          success: resPay,
          fail: rejPay,
        });
      });
      wx.showToast({ title: '支付成功', icon: 'success' });
      resolve(res);
    } catch (e) {
      wx.hideLoading();
      wx.showToast({ title: String((e && e.errMsg) || e), icon: 'none' });
      reject(e);
    }
  });
}

module.exports = {
  fetchMembershipSummary,
  openRenewPicker,
  payMembership,
};
