/**
 * 接口地址
 * 开发者工具：本地 http://127.0.0.1:5000
 * 真机/体验版/正式版：https://ggtaiqiu.com（须在微信公众平台配置 request 合法域名）
 * 本地真机联调：可在控制台执行 setManualApiBase('http://192.168.x.x:5000')
 */
const PORT = 5000;
const PROD_API = 'https://ggtaiqiu.com';
const LAN_IP = '192.168.0.101';
/** 当前球房 ID，与后台「球房会员」中一致；多球房部署时可按扫码参数覆盖 */
const VENUE_ID = 'V001';

function getApiBaseUrl() {
  const manual = wx.getStorageSync('manual_api_base');
  if (manual) return manual;

  // 默认连线上：桌台二维码 token 存于云托管 MySQL，开发者工具若连本地会导致「二维码无效」
  // 本地联调：控制台执行 require('./utils/config').setManualApiBase('http://127.0.0.1:5000')
  return PROD_API;
}

function setManualApiBase(url) {
  if (url) wx.setStorageSync('manual_api_base', url);
  else wx.removeStorageSync('manual_api_base');
}

module.exports = {
  PORT,
  PROD_API,
  LAN_IP,
  VENUE_ID,
  getApiBaseUrl,
  setManualApiBase,
};
