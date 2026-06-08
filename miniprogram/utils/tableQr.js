/** 解析球台扫码内容：小程序码 scene（T01:token）、页面路径或普通二维码 */

function safeDecode(text) {
  let s = String(text || '').trim();
  if (!s) return '';
  for (let i = 0; i < 2; i++) {
    try {
      if (/%[0-9A-Fa-f]{2}/.test(s)) {
        const next = decodeURIComponent(s);
        if (next === s) break;
        s = next;
      } else {
        break;
      }
    } catch (e) {
      break;
    }
  }
  return s;
}

function parseScenePair(text) {
  const s = safeDecode(text);
  const colon = s.indexOf(':');
  if (colon <= 0) return null;
  const tableId = s.slice(0, colon).trim();
  const qrToken = s.slice(colon + 1).trim();
  if (!tableId || !qrToken) return null;
  if (!/^T[\w-]+$/i.test(tableId)) return null;
  return { tableId, qrToken };
}

function parseTableScanResult(text) {
  let s = safeDecode(text);
  if (!s) return null;
  if (s.charAt(0) === '/') s = s.slice(1);

  const direct = parseScenePair(s);
  if (direct) return direct;

  if (s.includes('scene=')) {
    const sceneM = s.match(/[?&]scene=([^&]+)/i);
    if (sceneM && sceneM[1]) {
      const inner = parseTableScanResult(sceneM[1]);
      if (inner) return inner;
    }
  }

  if (s.includes('table_id=')) {
    const m = s.match(/table_id=([^&]+)/i);
    const t = s.match(/qr_token=([^&]+)/i);
    const tableId = m ? safeDecode(m[1]) : '';
    const qrToken = t ? safeDecode(t[1]) : '';
    if (tableId && qrToken) return { tableId, qrToken };
  }

  return null;
}

function extractSceneFromOptions(options) {
  if (!options) return '';
  return safeDecode(options.scene || (options.query && options.query.scene) || '');
}

function isTableScene(scene) {
  const s = safeDecode(scene);
  return /^T[\w-]+:/i.test(s);
}

module.exports = {
  safeDecode,
  parseScenePair,
  parseTableScanResult,
  extractSceneFromOptions,
  isTableScene,
};
