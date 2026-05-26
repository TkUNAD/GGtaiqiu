const publicApi = require('../../utils/publicApi');

Page({
  data: {
    phone: '',
    smsCode: '',
    password: '',
    confirm: '',
    codeSending: false,
    codeBtn: '获取验证码',
    loading: false,
  },

  onPhone(e) { this.setData({ phone: e.detail.value }); },
  onSms(e) { this.setData({ smsCode: e.detail.value }); },
  onPwd(e) { this.setData({ password: e.detail.value }); },
  onConfirm(e) { this.setData({ confirm: e.detail.value }); },

  async onSendCode() {
    if (this.data.codeSending) return;
    this.setData({ codeSending: true, codeBtn: '发送中...' });
    try {
      const d = await publicApi.sendResetCode(this.data.phone);
      let tip = '验证码已发送';
      if (d.dev_code) tip += `（开发: ${d.dev_code}）`;
      wx.showToast({ title: tip, icon: 'none', duration: 3000 });
      let n = 60;
      const t = setInterval(() => {
        n -= 1;
        if (n <= 0) {
          clearInterval(t);
          this.setData({ codeSending: false, codeBtn: '获取验证码' });
        } else {
          this.setData({ codeBtn: n + 's' });
        }
      }, 1000);
    } catch (e) {
      this.setData({ codeSending: false, codeBtn: '获取验证码' });
      wx.showToast({ title: String(e), icon: 'none' });
    }
  },

  async onSubmit() {
    this.setData({ loading: true });
    try {
      await publicApi.resetPassword({
        phone: this.data.phone,
        sms_code: this.data.smsCode,
        new_password: this.data.password,
        confirm_password: this.data.confirm,
      });
      wx.showModal({
        title: '已重置',
        content: '请使用手机号与新密码登录',
        showCancel: false,
      });
    } catch (e) {
      wx.showToast({ title: String(e), icon: 'none' });
    } finally {
      this.setData({ loading: false });
    }
  },
});
