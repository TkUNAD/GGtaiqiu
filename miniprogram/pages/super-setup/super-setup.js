const publicApi = require('../../utils/publicApi');

Page({
  data: {
    token: '',
    valid: false,
    errMsg: '',
    password: '',
    confirm: '',
    loading: false,
  },

  onLoad(options) {
    let token = (options && (options.token || options.scene)) || '';
    token = decodeURIComponent(token).trim();
    if (token.startsWith('sas_')) token = token.slice(4);
    this.setData({ token });
    this.verify(token);
  },

  async verify(token) {
    if (!token) {
      this.setData({ valid: false, errMsg: '未识别到初始化码，请重新下载并扫描最新二维码' });
      return;
    }
    try {
      await publicApi.verifySuperToken(token);
      this.setData({ valid: true, errMsg: '' });
    } catch (e) {
      const msg = String(e);
      let hint = msg;
      if (msg.indexOf('fail') >= 0 || msg.indexOf('timeout') >= 0 || msg.indexOf('网络') >= 0) {
        const app = getApp();
        hint = `无法连接服务器（${(app && app.globalData.baseUrl) || ''}）。真机请在开发者工具「详情-本地设置」把局域网 IP 改成电脑 ipconfig 中的地址，并确认 run.bat 已启动。`;
      } else if (msg.indexOf('无效') >= 0 || msg.indexOf('已使用') >= 0) {
        hint = `${msg}。请浏览器打开后端「/api/setup/super-init-qr.png」下载新码后再扫。`;
      }
      this.setData({ valid: false, errMsg: hint });
    }
  },

  onPwd(e) { this.setData({ password: e.detail.value }); },
  onConfirm(e) { this.setData({ confirm: e.detail.value }); },

  async onSubmit() {
    this.setData({ loading: true });
    try {
      await publicApi.completeSuperSetup({
        token: this.data.token,
        password: this.data.password,
        confirm_password: this.data.confirm,
      });
      wx.showModal({
        title: '设置成功',
        content: '请使用账号 admin 与新密码登录总后台',
        showCancel: false,
      });
    } catch (e) {
      wx.showToast({ title: String(e), icon: 'none' });
    } finally {
      this.setData({ loading: false });
    }
  },
});
