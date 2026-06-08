/** 解析球台扫码内容：小程序码 scene（T01:token）或明文链接 */
function parseTableScanResult(text) {
  const s = String(text || '').trim();
  if (!s) return null;

  const colon = s.indexOf(':');
  if (colon > 0 && /^T\d+$/i.test(s.slice(0, colon))) {
    return {
      tableId: s.slice(0, colon),
      qrToken: s.slice(colon + 1),
    };
  }

  if (s.includes('table_id=')) {
    const m = s.match(/table_id=([^&]+)/);
    const t = s.match(/qr_token=([^&]+)/);
    const tableId = m ? decodeURIComponent(m[1]) : '';
    const qrToken = t ? decodeURIComponent(t[1]) : '';
    if (tableId && qrToken) return { tableId, qrToken };
  }

  return null;
}

module.exports = {
  parseTableScanResult,
};
