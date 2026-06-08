const api = require('./api');
const { getApiBaseUrl } = require('./config');
const { getVenueId, setVenueId } = require('./venueStore');

function _isMissingApiError(err) {
  const msg = String(err || '');
  return (
    msg.indexOf('404') >= 0
    || msg.indexOf('接口不存在') >= 0
    || msg.indexOf('not found') >= 0
  );
}

/**
 * 校验桌台二维码并返回所属俱乐部；兼容未部署 qr-resolve 的旧后端。
 */
function resolveTableQr(tableId, qrToken) {
  const id = encodeURIComponent(tableId);
  const tokenQ = `qr_token=${encodeURIComponent(qrToken)}`;
  return api
    .request(`/api/table/${id}/qr-resolve?${tokenQ}`)
    .catch((err) => {
      if (!_isMissingApiError(err)) throw err;
      return api.request(`/api/table/${id}/scan-check?${tokenQ}&auto_venue=1`);
    })
    .catch((err) => {
      if (!_isMissingApiError(err)) throw err;
      const venueId = getVenueId();
      return api.request(
        `/api/table/${id}/scan-check?${tokenQ}&venue_id=${encodeURIComponent(venueId)}`
      );
    });
}

function applyResolvedVenue(info) {
  const venueId = (info && info.venue_id) || getVenueId();
  if (venueId) setVenueId(venueId, false);
  return venueId;
}

function formatScanError(err) {
  let content = String(err || '扫码失败');
  if (content.indexOf('二维码无效') >= 0) {
    content += '\n\n请到俱乐部后台「桌台管理」重新下载最新桌台二维码后再试（旧版打印码可能已失效）。';
    try {
      const sys = wx.getSystemInfoSync();
      const base = getApiBaseUrl();
      if (sys.platform === 'devtools' && /127\.0\.0\.1|localhost/i.test(base)) {
        content += '\n\n开发者工具当前连接本地后端，请改用线上接口 https://ggtaiqiu.com 后再扫码。';
      }
    } catch (e) {
      /* ignore */
    }
  }
  return content;
}

module.exports = {
  resolveTableQr,
  applyResolvedVenue,
  formatScanError,
};
