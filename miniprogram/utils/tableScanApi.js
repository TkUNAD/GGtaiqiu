const api = require('./api');
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

module.exports = {
  resolveTableQr,
  applyResolvedVenue,
};
