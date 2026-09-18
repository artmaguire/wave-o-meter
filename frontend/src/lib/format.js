// Formatting + rating helpers shared across components.

export const RATING_LABELS = [
  'No surf', 'Very poor', 'Poor', 'Fair', 'Good', 'Very good'
];

// Map a 0-5 score to its colour band CSS variable.
export function ratingColor(score) {
  if (score == null) return 'var(--border)';
  const band = Math.max(0, Math.min(5, Math.round(score)));
  return `var(--r${band})`;
}

export function ratingBand(score) {
  if (score == null) return null;
  return Math.max(0, Math.min(5, Math.floor(score + 0.5)));
}

// Compass arrow: direction is where it comes FROM; arrow points where it goes TO.
export function dirArrow(deg) {
  if (deg == null) return '';
  return `rotate(${(deg + 180) % 360}deg)`;
}

export function fmtTime(iso) {
  // Times are already Irish local wall-clock (backend fetches Europe/Dublin).
  // Read straight from the string so the displayed hour is correct regardless
  // of the viewing device's own timezone.
  const m = iso.match(/T(\d{2}):(\d{2})/);
  if (!m) return iso;
  let h = parseInt(m[1], 10);
  const min = m[2];
  const ampm = h >= 12 ? 'pm' : 'am';
  h = h % 12 || 12;
  return `${h}:${min}${ampm}`;
}

export function fmtDay(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
}

export const CONF_LABEL = {
  high: 'High confidence',
  medium: 'Medium confidence',
  low: 'Low confidence',
  long_range: 'Long-range outlook'
};

// Short confidence label + dot colour for compact display on the home card.
export const CONF_SHORT = {
  high: 'High', medium: 'Med', low: 'Low', long_range: 'Outlook'
};
export const CONF_COLOR = {
  high: 'var(--r4)', medium: 'var(--r3)', low: 'var(--r2)',
  long_range: 'var(--text-dim)'
};

export function fmtHeight(m) {
  if (m == null) return '–';
  return `${m.toFixed(1)} m`;
}

// Surf (face) height in feet. The model gives significant wave height (Hs) —
// the open-ocean swell — but surfers quote the breaking face at the beach,
// which is smaller. ~0.6x Hs gives believable surf faces (3m swell -> ~6ft).
// Scoring still uses raw Hs; this is display only.
const SURF_FACE_FACTOR = 0.6;
export function mToFt(m) {
  if (m == null) return null;
  return m * 3.281 * SURF_FACE_FACTOR;
}
export function fmtFtRange(minM, maxM) {
  if (minM == null || maxM == null) return '–';
  const lo = Math.round(mToFt(minM));
  const hi = Math.round(mToFt(maxM));
  return lo === hi ? `${lo} ft` : `${lo}-${hi} ft`;
}
export function fmtFt(m) {
  if (m == null) return '–';
  return `${mToFt(m).toFixed(1)} ft`;
}

export const PART_LABEL = { morning: 'AM', afternoon: 'MID', evening: 'PM' };

export function fmtDayFull(iso) {
  const d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString([], { weekday: 'long' });
}
export function fmtDayShort(iso) {
  const d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString([], { weekday: 'short' });
}

// Quality symbol for a 0-5 score (used on the decluttered home cards).
// Shape conveys quality; colour reinforces it (colour-blind safe pairing).
export function qualitySymbol(score) {
  if (score == null) return '·';
  const b = Math.max(0, Math.min(5, Math.round(score)));
  return ['✕', '▂', '▄', '▅', '▇', '★'][b];
}
// Confidence symbol (filled circle = high, half = med, open = low, dash = outlook)
export const CONF_SYMBOL = {
  high: '●', medium: '◐', low: '○', long_range: '·'
};

// m/s -> km/h (wind is fetched in m/s for scoring; displayed in km/h).
export function msToKmh(ms) {
  if (ms == null) return null;
  return Math.round(ms * 3.6);
}
