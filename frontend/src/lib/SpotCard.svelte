<script>
  import { ratingColor, fmtFtRange, CONF_COLOR, CONF_SYMBOL } from './format.js';
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
</script>

<a class="card" href="/spot/{spot.id}" aria-label="View {spot.name} forecast">
  <h3>
    {spot.name}
    {#if trend}<span class="trend {trend.cls}" title={trend.title}>{trend.icon}</span>{/if}
    {#if spot.stale}<span class="flag" title="showing last cached">· cached</span>{/if}
  </h3>
  {#if spot.pending}
    <p class="pending muted">Loading forecast…</p>
  {:else}
    <div class="scroller" use:scrollSync={'calendar'}>
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

  /* synced horizontal scroller; hide the scrollbar (the top calendar shows position) */
  .scroller { display: flex; gap: var(--sp-3); overflow-x: auto;
    -webkit-overflow-scrolling: touch; scrollbar-width: none; }
  .scroller::-webkit-scrollbar { display: none; }
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
