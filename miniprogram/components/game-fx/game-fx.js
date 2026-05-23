const { getTierImage } = require('../../utils/tierIcons');

const DURATION_MS = 4000;

function makeShards(n) {
  return Array.from({ length: n }, (_, i) => ({
    id: i,
    rot: (360 / n) * i + (i % 3) * 15,
    dist: 60 + (i % 5) * 36,
    delay: (i % 6) * 0.05,
    size: 16 + (i % 4) * 10,
    left: 38 + (i * 7) % 24,
  }));
}

function makeEmbers(n) {
  return Array.from({ length: n }, (_, i) => ({
    id: i,
    left: 15 + (i * 11) % 70,
    top: 35 + (i * 9) % 40,
    delay: (i % 8) * 0.12,
    dur: 0.6 + (i % 4) * 0.15,
  }));
}

Component({
  properties: {
    type: { type: String, value: '' },
    oldTier: { type: Number, value: 1 },
    newTier: { type: Number, value: 1 },
  },

  data: {
    visible: false,
    shards: [],
    embers: [],
    oldSrc: '',
    newSrc: '',
    tierPhase: 'old',
  },

  lifetimes: {
    detached() {
      this._clearTimer();
    },
  },

  observers: {
    type(t) {
      if (!t) {
        this._clearTimer();
        this.setData({ visible: false, tierPhase: 'old' });
        return;
      }
      this._play(t);
    },
  },

  methods: {
    noop() {},

    _clearTimer() {
      if (this._timer) {
        clearTimeout(this._timer);
        this._timer = null;
      }
      if (this._tierTimer) {
        clearTimeout(this._tierTimer);
        this._tierTimer = null;
      }
    },

    _play(t) {
      this._clearTimer();
      const base = {
        visible: true,
        shards: makeShards(t === 'lose' ? 22 : 14),
        embers: makeEmbers(12),
        tierPhase: 'old',
      };
      if (t === 'tierUp') {
        const oldTier = Math.max(1, Math.min(6, this.properties.oldTier || 1));
        const newTier = Math.max(1, Math.min(6, this.properties.newTier || oldTier));
        this.setData({
          ...base,
          oldSrc: getTierImage(oldTier),
          newSrc: getTierImage(newTier),
        });
        this._tierTimer = setTimeout(() => {
          this.setData({ tierPhase: 'smash' });
        }, 900);
      } else {
        this.setData(base);
      }
      this._timer = setTimeout(() => {
        this.setData({ visible: false, tierPhase: 'old' });
        this.triggerEvent('done');
      }, DURATION_MS);
    },
  },
});
