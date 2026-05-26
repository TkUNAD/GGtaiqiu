/** 小程序内可展示的头像 URL */
const { getApiBaseUrl } = require('./config');

const DEFAULT_AVATAR = '/assets/default-avatar.png';

function isEphemeralAvatar(url) {
  const u = (url || '').trim().toLowerCase();
  if (!u) return true;
  if (u.startsWith('wxfile://') || u.startsWith('wxlocalresource://')) return true;
  if ((u.startsWith('http://tmp/') || u.startsWith('https://tmp/'))) return true;
  return false;
}

function resolveDisplayAvatar(url, options) {
  const opts = options || {};
  const u = (url || '').trim();
  if (!u || isEphemeralAvatar(u)) {
    if (opts.allowLocal && u && !isEphemeralAvatar(u)) return u;
    return DEFAULT_AVATAR;
  }
  if (u.startsWith('/assets/')) return u;
  if (u.startsWith('/static/')) {
    const base = getApiBaseUrl().replace(/\/$/, '');
    return base + u;
  }
  if (u.startsWith('https://') || u.startsWith('http://')) return u;
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
