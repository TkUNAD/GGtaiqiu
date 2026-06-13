const WARN_M = 50;

function toRad(deg) {
  return (deg * Math.PI) / 180;
}

function haversineMeters(lat1, lng1, lat2, lng2) {
  const R = 6371000;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function resolveDistanceM(venue, location) {
  if (!venue || !location) return null;
  if (venue.distance_m != null) return venue.distance_m;
  const lat = venue.latitude;
  const lng = venue.longitude;
  if (lat == null || lng == null) return null;
  try {
    return Math.round(
      haversineMeters(
        Number(location.latitude),
        Number(location.longitude),
        Number(lat),
        Number(lng),
      ),
    );
  } catch (e) {
    return null;
  }
}

function enrichVenuesWithDistance(venues, location) {
  if (!venues || !venues.length) return [];
  const list = venues.map((v) => {
    const distance_m = resolveDistanceM(v, location);
    const has_location = v.has_location || (v.latitude != null && v.longitude != null);
    return Object.assign({}, v, {
      distance_m: distance_m != null ? distance_m : v.distance_m,
      has_location,
    });
  });
  list.sort((a, b) => {
    if (a.distance_m == null && b.distance_m == null) {
      return String(a.name || '').localeCompare(String(b.name || ''));
    }
    if (a.distance_m == null) return 1;
    if (b.distance_m == null) return -1;
    return a.distance_m - b.distance_m;
  });
  return list;
}

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
  const m = resolveDistanceM(venue, location);
  if (m == null) {
    return { distanceM: null, distanceText: '', distanceWarning: false };
  }
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
  enrichVenuesWithDistance,
  WARN_M,
};
