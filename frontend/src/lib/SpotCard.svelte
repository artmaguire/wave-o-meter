<script>
  import { ratingColor, fmtFtRange, fmtFt, CONF_COLOR, CONF_SYMBOL } from './format.js';
  import { scrollSync } from './scrollSync.js';
  // props: spot overview { id, name, display_name, current, days[7] }
  let { spot } = $props();
  const days = $derived((spot.days ?? []).slice(0, 7));
  const TREND = {
    improving: { icon: '↗', cls: 'up', title: 'improving over the next few hours' },
    dropping: { icon: '↘', cls: 'down', title: 'dropping over the next few hours' },
    steady: { icon: '→', cls: 'flat', title: 'holding steady' }
  };
  const trend = $derived(TREND[spot.trend] ?? null);
  const swell = $derived((spot.current ?? {}).swell ?? null);

  // Surfline-style wave silhouette: a filled area whose top edge traces each
  // day's swell height across the week, drawn behind the day columns.
  const wavePoints = $derived.by(() => {
    const n = days.length;
    if (!n) return '';
    const hs = days.map((d) => d.height_max ?? d.height_min ?? 0);
    const max = Math.max(1, ...hs);
    // x at each day-column centre (0..100); y: taller swell -> higher (lower y).
    // Keep it a gentle band: amplitude ~55% of height, floor offset so small
    // days still show some wave.
    const pts = hs.map((h, i) => {
      const x = ((i + 0.5) / n) * 100;
      const y = 100 - (18 + 0.55 * (h / max) * 100);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    return `0,100 0,${(100 - 18).toFixed(1)} ${pts.join(' ')} 100,${(100 - 18).toFixed(1)} 100,100`;
  });
</script>

<a class="card" href="/spot/{spot.id}" aria-label="View {spot.name} forecast">
  <h3>
    {spot.name}
    {#if trend}<span class="trend {trend.cls}" title={trend.title}>{trend.icon}</span>{/if}
    {#if spot.stale}<span class="flag" title="showing last cached">· cached</span>{/if}
  </h3>
  {#if swell}
    <div class="nowline">
      <span class="nowh">{fmtFt(swell.height_m)}</span>
      {#if swell.period_s}<span class="nowp">@ {swell.period_s}s</span>{/if}
      {#if swell.direction_compass}<span class="nowd">{swell.direction_compass}</span>{/if}
      <span class="nowlabel muted">now</span>
    </div>
  {/if}
  {#if spot.pending}
    <p class="pending muted">Loading forecast…</p>
  {:else}
    <div class="scroller" use:scrollSync={'calendar'}>
      <div class="wave-track">
        <svg class="wave" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <polygon points={wavePoints} />
        </svg>
        <div class="cells">
          {#each days as day}
            <div class="cell">
              <span class="ft">{fmtFtRange(day.height_min, day.height_max)}</span>
              <span class="bars">
                {#each day.parts as p}
                  <span class="bar" style="background:{ratingColor(p.score)}"></span>
                {/each}
              </span>
              <span class="conf" style="color:{CONF_COLOR[day.parts[1]?.confidence] ?? 'var(--text-dim)'}"
                title="confidence">{CONF_SYMBOL[day.parts[1]?.confidence] ?? '·'}</span>
            </div>
          {/each}
        </div>
      </div>
    </div>
  {/if}
</a>

<style>
  .card {
    display: block;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: var(--sp-3) var(--sp-4);
    margin-bottom: var(--sp-3);
  }
  h3 { font-size: 1.1rem; margin-bottom: var(--sp-3); }
  .trend { font-size: .95rem; margin-left: 4px; }
  .trend.up { color: var(--r4); }
  .trend.down { color: var(--r2); }
  .trend.flat { color: var(--text-dim); }
  .nowline { display: flex; align-items: baseline; gap: 6px; margin: -4px 0 var(--sp-3); }
  .nowh { font-size: 1rem; font-weight: 600; }
  .nowp, .nowd { font-size: .82rem; color: var(--text-dim); }
  .nowlabel { font-size: .7rem; text-transform: uppercase; letter-spacing: .04em; margin-left: auto; }

  /* synced horizontal scroller; hide the scrollbar (the top calendar shows position) */
  .scroller { display: flex; gap: var(--sp-3); overflow-x: auto;
    -webkit-overflow-scrolling: touch; scrollbar-width: none; }
  .scroller::-webkit-scrollbar { display: none; }
  /* wave silhouette behind the day columns, scrolls with them */
  .wave-track { position: relative; display: inline-flex; }
  .wave { position: absolute; inset: 0; width: 100%; height: 100%; }
  .wave polygon { fill: color-mix(in srgb, var(--accent) 24%, var(--bg-elev)); }
  .cells { position: relative; z-index: 1; display: flex; gap: var(--sp-3);
    padding: var(--sp-2) 0; }

  /* fixed column width so cells line up with the shared day header */
  .cell { flex: 0 0 var(--day-col, 64px); display: flex; flex-direction: column;
    align-items: center; gap: 5px; }
  .ft { font-size: .82rem; font-weight: 600; white-space: nowrap; }
  .bars { display: flex; gap: 3px; width: 100%; justify-content: center; }
  .bar { flex: 1; height: 11px; border-radius: 3px; }
  .conf { font-size: .72rem; line-height: 1; }
  .pending { font-size: .85rem; padding: var(--sp-2) 0; }
  .flag { font-size: .7rem; color: var(--text-dim); margin-left: 6px; font-weight: 400; }
</style>
