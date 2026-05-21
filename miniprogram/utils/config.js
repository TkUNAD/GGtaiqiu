/**
 * 接口地址
 * 真机/预览：必须用电脑局域网 IP（ipconfig 里 192.168.x.x）
 * 勿用 198.18.x（Clash/VPN 虚拟网卡，手机连不上）
 * 正式版小程序必须使用 HTTPS 后端（微信要求），请在微信公众平台配置合法域名
 */
const PORT = 5000;
const LAN_IP = '192.168.0.108';
/** 当前球房 ID，与后台「球房会员」中一致；多球房部署时可按扫码参数覆盖 */
const VENUE_ID = 'V001';

function getApiBaseUrl() {
  const manual = wx.getStorageSync('manual_api_base');
  if (manual) return manual;

  try {
    const sys = wx.getSystemInfoSync();
    if (sys.platform === 'devtools') {
      return `http://127.0.0.1:${PORT}`;
    }
  } catch (e) {
    // ignore
  }
  return `http://${LAN_IP}:${PORT}`;
}

function setManualApiBase(url) {
  if (url) wx.setStorageSync('manual_api_base', url);
  else wx.removeStorageSync('manual_api_base');
}

module.exports = {
  PORT,
  LAN_IP,
  VENUE_ID,
  getApiBaseUrl,
  setManualApiBase,
};
