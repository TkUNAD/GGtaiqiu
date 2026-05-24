const WARN_M = 50;

function ensureLocation(app) {
  if (app.globalData.location) {
    return Promise.resolve(app.globalData.location);
  }
  return new Promise((resolve, reject) => {
    wx.getLocation({
      type: 'gcj02',
      success(res) {
        const loc = { latitude: res.latitude, longitude: res.longitude };
        app.globalData.location = loc;
        resolve(loc);
      },
      fail(err) {
        app.globalData.location = null;
        reject(err);
      },
    });
  });
}

function pickVenueFromList(venues, manualId, isManual) {
  if (!venues || !venues.length) return null;
  if (isManual && manualId) {
    const found = venues.find((v) => v.id === manualId);
    if (found) return found;
  }
  const withLoc = venues.filter((v) => v.has_location && v.distance_m != null);
  if (withLoc.length) return withLoc[0];
  return venues[0];
}

function buildDistanceState(venue, location) {
  if (!venue || !location || venue.distance_m == null || !venue.has_location) {
    return { distanceM: null, distanceText: '', distanceWarning: false };
  }
  const m = venue.distance_m;
  let distanceText = '';
  if (m < 1000) distanceText = `约 ${m} 米`;
  else distanceText = `约 ${(m / 1000).toFixed(1)} 公里`;
  return {
    distanceM: m,
    distanceText,
    distanceWarning: m > WARN_M,
  };
}

module.exports = {
  ensureLocation,
  pickVenueFromList,
  buildDistanceState,
  WARN_M,
};
