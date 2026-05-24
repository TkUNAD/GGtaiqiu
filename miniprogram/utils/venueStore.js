const { VENUE_ID } = require('./config');

const STORAGE_VENUE_ID = 'selected_venue_id';
const STORAGE_MANUAL = 'venue_manual_pick';

function getVenueId() {
  return wx.getStorageSync(STORAGE_VENUE_ID) || VENUE_ID;
}

function isManualPick() {
  return !!wx.getStorageSync(STORAGE_MANUAL);
}

function setVenueId(venueId, manualPick = true) {
  const id = venueId || VENUE_ID;
  wx.setStorageSync(STORAGE_VENUE_ID, id);
  if (manualPick) {
    wx.setStorageSync(STORAGE_MANUAL, '1');
  } else {
    wx.removeStorageSync(STORAGE_MANUAL);
  }
  const app = getApp();
  if (app) {
    app.globalData.venueId = id;
    if (typeof app.loadVenueStatus === 'function') {
      app.loadVenueStatus();
    }
  }
  return id;
}

function clearManualPick() {
  wx.removeStorageSync(STORAGE_MANUAL);
}

function formatDistance(m) {
  if (m == null || m === '') return '';
  const n = Number(m);
  if (Number.isNaN(n)) return '';
  if (n < 1000) return `${n}米`;
  return `${(n / 1000).toFixed(1)}公里`;
}

module.exports = {
  getVenueId,
  isManualPick,
  setVenueId,
  clearManualPick,
  formatDistance,
  DISTANCE_WARN_M: 50,
};
