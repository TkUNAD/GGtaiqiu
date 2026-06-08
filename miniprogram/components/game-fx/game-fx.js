const { getTierImage } = require('../../utils/tierIcons');

const DURATION_MS = 4000;

function makeShards(n) {
  return Array.from({ length: n }, (_, i) => ({
    id: i,
    rot: (360 / n) * i + (i % 3) * 15,
    delay: (i % 6) * 0.05,
  }));
}

function makeParticles(n, kind) {
  return Array.from({ length: n }, (_, i) => ({
    id: i,
    left: 8 + (i * 17) % 84,
    top: kind === 'win' ? 50 + (i * 13) % 40 : 0,
    delay: (i % 10) * 0.08,
    size: 10 + (i % 5) * 6,
  }));
}

Component({
  properties: {
    fxKind: { type: String, value: '' },
    oldTier: { type: Number, value: 1 },
    newTier: { type: Number, value: 1 },
  },

  data: {
    visible: false,
    shards: [],
    particles: [],
    oldSrc: '',
    newSrc: '',
    tierPhase: 'old',
  },

  lifetimes: {
    attached() {
      const kind = this.properties.fxKind;
      if (kind) this._play(kind);
    },
    detached() {
      this._clearTimer();
    },
  },

  observers: {
    fxKind(kind, oldKind) {
      if (!kind) {
        this._clearTimer();
        this.setData({ visible: false, tierPhase: 'old' });
        return;
      }
      if (oldKind !== undefined && oldKind !== '' && kind !== oldKind) {
        this._play(kind);
      }
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
      const particles = makeParticles(t === 'lose' ? 18 : 14, t);
      const base = {
        visible: true,
        shards: makeShards(12),
        particles,
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
