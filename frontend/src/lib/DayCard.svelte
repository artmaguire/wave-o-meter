<script>
  import { ratingColor, dirArrow, fmtFtRange, fmtDayShort, fmtDayFull } from './format.js';
  // props:
  //   day: { date, parts[3], height_min, height_max }
  //   full: use full weekday name + larger (detail page); else compact (home)
  //   selected, onselect: for the detail scrubber
  let { day, full = false, selected = false, onselect = null } = $props();
  const parts = $derived(day.parts ?? []);
</script>

<button
  class="day"
  class:full
  class:selected
  onclick={() => onselect?.(day)}
  disabled={!onselect}
  aria-label="{fmtDayFull(day.date)} {fmtFtRange(day.height_min, day.height_max)}"
>
  <div class="label">{full ? fmtDayFull(day.date) : fmtDayShort(day.date)}</div>
  <div class="height">{fmtFtRange(day.height_min, day.height_max)}</div>

  <!-- three wind arrows (one per daypart) -->
  <div class="arrows">
    {#each parts as p}
      <span class="arrow" title={p.part}>
        {#if p.wind_dir != null}
          <svg viewBox="0 0 24 24" style="transform:{dirArrow(p.wind_dir)}">
            <path d="M12 3 L12 21 M12 3 L7 9 M12 3 L17 9" />
          </svg>
        {:else}·{/if}
      </span>
    {/each}
  </div>

  <!-- three rating bars (one per daypart) -->
  <div class="bars">
    {#each parts as p}
      <span class="bar" style="background:{ratingColor(p.score)}"></span>
    {/each}
  </div>
</button>

<style>
  .day {
    flex: 0 0 auto;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: var(--sp-3);
    text-align: center;
    min-width: 92px;
    cursor: default;
    font: inherit; color: inherit;
  }
  .day.full { min-width: 104px; }
  .day[disabled] { cursor: default; }
  .day:not([disabled]) { cursor: pointer; }
  .day.selected { border-color: var(--text); background: var(--bg-elev); }

  .label { font-size: .8rem; color: var(--text-dim); font-weight: 500; }
  .full .label { font-size: .9rem; color: var(--text); }
  .height { font-size: 1.15rem; font-weight: 600; margin-top: 2px; }
  .full .height { font-size: 1.35rem; }

  .arrows { display: flex; justify-content: space-around; gap: 4px; margin-top: var(--sp-3); }
  .arrow { width: 16px; height: 16px; color: var(--text-dim); }
  .arrow svg { width: 100%; height: 100%; fill: none; stroke: currentColor;
    stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }

  .bars { display: flex; justify-content: space-around; gap: 4px; margin-top: var(--sp-2); }
  .bar { flex: 1; height: 6px; border-radius: 3px; }
  .full .bar { height: 8px; }
</style>
