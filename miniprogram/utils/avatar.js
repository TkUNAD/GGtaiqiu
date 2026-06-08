/** 小程序内可展示的头像 URL */
const { getApiBaseUrl, PROD_API } = require('./config');

const DEFAULT_AVATAR = '/assets/default-avatar.png';

function isEphemeralAvatar(url) {
  const u = (url || '').trim().toLowerCase();
  if (!u) return true;
  if (u.startsWith('wxfile://') || u.startsWith('wxlocalresource://')) return true;
  if ((u.startsWith('http://tmp/') || u.startsWith('https://tmp/'))) return true;
  return false;
}

function _toHttpsIfProdHost(url) {
  if (!url || !url.startsWith('http://')) return url;
  const host = url.replace(/^https?:\/\//i, '').split('/')[0].toLowerCase();
  const prodHost = (PROD_API || '').replace(/^https?:\/\//i, '').replace(/\/$/, '').toLowerCase();
  if (prodHost && (host === prodHost || host.endsWith('.' + prodHost))) {
    return 'https://' + url.slice(7);
  }
  return url;
}

function resolveDisplayAvatar(url, options) {
  const opts = options || {};
  let u = (url || '').trim();
  if (!u || isEphemeralAvatar(u)) {
    if (opts.allowLocal && u && !isEphemeralAvatar(u)) return u;
    return DEFAULT_AVATAR;
  }

  const base = getApiBaseUrl().replace(/\/$/, '');
  const prod = (PROD_API || 'https://ggtaiqiu.com').replace(/\/$/, '');
  u = u.replace(/^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?/i, prod);

  if (u.startsWith('/assets/')) return u;
  if (u.startsWith('/static/')) return base + u;
  if (u.startsWith('http://')) return _toHttpsIfProdHost(u);
  if (u.startsWith('https://')) return u;
  return DEFAULT_AVATAR;
}

/** 本地临时头像转 base64，供登录上传 */
function readLocalAvatarBase64(filePath) {
  return new Promise((resolve) => {
    const p = (filePath || '').trim();
    if (!p || (!p.startsWith('wxfile://') && p.indexOf('tmp') < 0 && !p.startsWith('http://tmp'))) {
      resolve('');
      return;
    }
    try {
      wx.getFileSystemManager().readFile({
        filePath: p,
        encoding: 'base64',
        success: (res) => resolve(res.data || ''),
        fail: () => resolve(''),
      });
    } catch (e) {
      resolve('');
    }
  });
}

module.exports = {
  DEFAULT_AVATAR,
  resolveDisplayAvatar,
  readLocalAvatarBase64,
  isEphemeralAvatar,
};
