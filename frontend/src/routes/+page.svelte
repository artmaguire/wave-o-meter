<script>
  import { onMount } from 'svelte';
  import { getOverview, getSummary, getAccuracy } from '$lib/api.js';
  import SpotCard from '$lib/SpotCard.svelte';
  import { scrollSync } from '$lib/scrollSync.js';
  import {
    RATING_LABELS, ratingColor, qualitySymbol,
    CONF_SYMBOL, fmtDayShort
  } from '$lib/format.js';

  let data = $state(null);
  let error = $state(null);
  let loading = $state(true);

  async function load() {
    loading = true; error = null;
    try { data = await getOverview(); }
    catch (e) { error = e.message; }
    finally { loading = false; }
  }
  // Render **bold** markers from the summary text (content is app-generated).
  function md(text) {
    return String(text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  }

  // "Spot — Day part: Quality (n/5), H ft" -> parts for a richer row
  function parseBest(line) {
    const m = String(line).match(/^(.+?)\s+—\s+(.+?):\s+(.+?)\s+\((\d)\/5\),\s+(.+)$/);
    if (!m) return { raw: line };
    return { spot: m[1], when: m[2], quality: m[3], score: Number(m[4]), size: m[5] };
  }
  const PART_ICON = { morning: '🌅', midday: '☀️', evening: '🌇' };
  function partIcon(when) {
    const w = String(when).toLowerCase();
    for (const k of Object.keys(PART_ICON)) if (w.includes(k)) return PART_ICON[k];
    return '🏄';
  }

  let accuracy = $state(null);
  async function loadAccuracy() {
    try { accuracy = await getAccuracy(); } catch { accuracy = null; }
  }
  onMount(load);
  onMount(loadAccuracy);

  // Shared calendar header dates (from the first available spot).
  const headerDays = $derived.by(() => {
    for (const c of data?.counties ?? [])
      for (const sp of c.spots)
        if (sp.days?.length) return sp.days.slice(0, 7).map((d) => d.date);
    return [];
  });

  // Summary modal
  let showSummary = $state(false);
  let summary = $state(null);
  let summaryLoading = $state(false);
  async function openSummary() {
    showSummary = true;
    if (summary) return;
    summaryLoading = true;
    try { summary = await getSummary(); }
    catch (e) { summary = { error: e.message }; }
    finally { summaryLoading = false; }
  }

</script>

<div class="container">
  <header>
    <div>
      <h1>Wave-o-meter</h1>
    </div>
    <button class="summary-btn" onclick={openSummary}>✨ Summary</button>
  </header>

  {#if loading}
    <p class="muted">Loading conditions…</p>
  {:else if error}
    <div class="err">
      <p>Couldn't load forecasts: {error}</p>
      <button onclick={load}>Retry</button>
    </div>
  {:else if data}
    <!-- shared calendar: scrolls all spots in sync -->
    {#if headerDays.length}
      <div class="calbar">
        <div class="calspacer"></div>
        <div class="calscroll" use:scrollSync={'calendar'}>
          {#each headerDays as d}
            <div class="calday">
              <span class="dow">{fmtDayShort(d)}</span>
              <span class="dnum">{new Date(d + 'T12:00:00').getDate()}</span>
            </div>
          {/each}
        </div>
      </div>
    {/if}

    {#each data.counties as county}
      <section>
        <h2 class="county">{county.county}</h2>
        {#each county.spots as spot}
          <SpotCard {spot} />
        {/each}
      </section>
    {/each}
    <details class="legend">
      <summary>How to read the forecast</summary>
      <p>Each row is a spot; scroll the <strong>calendar</strong> at the top to move
        all spots through the next 7 days together. Each day has three
        <strong>bars</strong> — morning, midday, evening. Colour is the
        <strong>0–5 surf rating</strong>:</p>
      <div class="scale">
        {#each RATING_LABELS as lbl, i}
          <span class="chip"><span class="sw" style="background:{ratingColor(i)}"></span>{i} {lbl}</span>
        {/each}
      </div>
      <p>The number is the forecast <strong>surf height</strong> (feet). The small
        symbol under each day is <strong>forecast confidence</strong>:</p>
      <div class="scale">
        <span class="chip">{CONF_SYMBOL.high} High</span>
        <span class="chip">{CONF_SYMBOL.medium} Medium</span>
        <span class="chip">{CONF_SYMBOL.low} Low</span>
        <span class="chip">{CONF_SYMBOL.long_range} Long-range</span>
      </div>
      <p>Tap a spot for the hour-by-hour detail. In there you'll also see:</p>
      <ul class="legend-list">
        <li><strong>Sea</strong> — <em>clean</em> means long-period groundswell
          (better-shaped, cleaner waves); <em>choppy</em> means wind-driven sea
          (messier). Clean swell scores higher than choppy of the same size.</li>
        <li><strong>Swell / Wind / Tide</strong> — the raw conditions per hour,
          with wind shown as offshore (good), cross-shore, or onshore (poor).</li>
        <li><strong>Wave height</strong> — the <em>total</em> sea state (groundswell
          plus local wind chop) converted to surf-face feet, i.e. roughly what
          you'd see in the water. The Sea column tells you which of the two is
          dominant.</li>
        <li><strong>Power</strong> — how hard the waves hit, from height and period
          (power rises with the <em>square</em> of height and with period, so a
          long-period swell packs far more punch than a short one the same size).
          <em>gentle</em> → soft and small; <em>moderate</em> → normal beach-break
          energy; <em>punchy</em> → solid, holds a good wall; <em>powerful</em> /
          <em>heavy</em> → serious force, experience and the right board needed.</li>
        <li><strong>★ Best time</strong> — the top daylight hour to surf that day,
          with a plain-English reason (offshore wind, favourable tide, etc.).</li>
        <li><strong>Air / Sea temp &amp; wetsuit</strong> — plus sunrise, sunset
          and UV in the day's conditions strip.</li>
        <li><strong>Your sessions</strong> — log what it was really like; over time
          this tunes the forecast to your spots.</li>
      </ul>
      <p class="muted small">Forecasts open-ocean conditions, not the exact wave on
        the sandbank — a strong guide, not a guarantee.</p>
    </details>

    {#if accuracy?.buoys?.length}
      <section class="accuracy">
        <h2 class="county">Model accuracy (last {accuracy.buoys[0].window_days} days)</h2>
        {#each accuracy.buoys as b}
          <div class="acc-buoy">
            <div class="acc-label">{b.label} <span class="muted">({b.buoy})</span></div>
            {#each b.models as m}
              <div class="acc-row" class:best={m.model === b.best}>
                <span class="acc-model">{m.model.replace('_wam025','').replace('_wave','')}</span>
                <span class="acc-mae">±{m.mae} m</span>
                <span class="acc-corr">r={m.corr}</span>
                {#if m.model === b.best}<span class="acc-tag">best</span>{/if}
              </div>
            {/each}
          </div>
        {/each}
        <p class="muted small">How closely each forecast model matched the measured
          buoy over the last {accuracy.buoys[0].window_days} days (lower ± = more accurate).</p>
      </section>
    {/if}

    <p class="foot muted">
      Forecasts open-ocean conditions (swell, wind, tide) — not the exact wave on
      the sandbank. Days 8+ (in the spot view) are lower confidence.
    </p>
  {/if}

  {#if showSummary}
    <div class="modal-bg" onclick={() => showSummary = false} role="presentation">
      <div class="modal" onclick={(e) => e.stopPropagation()} role="dialog" aria-label="Forecast summary">
        <div class="modal-head">
          <h2>Forecast summary</h2>
          <button class="x" onclick={() => showSummary = false} aria-label="Close">✕</button>
        </div>
        <div class="modal-body">
        {#if summaryLoading}
          <p class="muted">Summarising…</p>
        {:else if summary?.error}
          <p class="err">Couldn't build summary: {summary.error}</p>
        {:else if summary}
          {#if summary.verdict}<p class="verdict">{@html md(summary.verdict)}</p>{/if}

          <h3>Right now</h3>
          <ul>{#each summary.current as l}<li>{l}</li>{/each}</ul>

          <h3>Best windows (next 7 days)</h3>
          <ul class="bestlist">
            {#each summary.best as l}
              {@const b = parseBest(l)}
              {#if b.raw}
                <li>{b.raw}</li>
              {:else}
                <li class="bestrow">
                  <span class="bscore" style="background:{ratingColor(b.score)}">{b.score}</span>
                  <span class="bmain">
                    <span class="bspot">{b.spot}</span>
                    <span class="bwhen">{partIcon(b.when)} {b.when}</span>
                  </span>
                  <span class="bmeta">
                    <span class="bqual" style="color:{ratingColor(b.score)}">{b.quality}</span>
                    <span class="bsize">🌊 {b.size}</span>
                  </span>
                </li>
              {/if}
            {/each}
          </ul>

          <h3>How it's changing</h3>
          {#each summary.outlook as para}
            <p class="outlook">{@html md(para)}</p>
          {/each}
        {/if}
        </div>
      </div>
    </div>
  {/if}
</div>

<style>
  header { padding: var(--sp-4) 0 var(--sp-4); display: flex;
    justify-content: space-between; align-items: center; gap: var(--sp-3); }
  h1 { font-size: 1.7rem; }
  header p { margin: var(--sp-2) 0 0; }
  .summary-btn { background: transparent; color: var(--accent);
    border: 1px solid color-mix(in srgb, var(--accent) 45%, transparent);
    border-radius: 999px; padding: 7px 14px; font: inherit; font-size: .85rem;
    font-weight: 600; cursor: pointer; white-space: nowrap; flex: 0 0 auto;
    transition: background .15s ease; }
  .summary-btn:active { background: color-mix(in srgb, var(--accent) 15%, transparent); }

  /* summary modal */
  .modal-bg { position: fixed; inset: 0; background: rgba(0,0,0,.6);
    display: flex; align-items: flex-end; justify-content: center; z-index: 50; }
  .modal { background: var(--bg-elev); border: 1px solid var(--border);
    border-radius: var(--radius) var(--radius) 0 0; width: 100%; max-width: var(--maxw);
    max-height: 85vh; padding: 0; animation: slideup .2s ease;
    display: flex; flex-direction: column; overflow: hidden; }
  /* header is a flex sibling, so it stays put while only the body scrolls */
  .modal-body { overflow-y: auto; -webkit-overflow-scrolling: touch;
    padding: 0 var(--sp-4) var(--sp-6); }
  @keyframes slideup { from { transform: translateY(100%); } to { transform: none; } }
  .modal-head { display: flex; justify-content: space-between; align-items: center;
    flex: 0 0 auto; background: var(--bg-elev); padding: var(--sp-4) var(--sp-4) var(--sp-3);
    border-bottom: 1px solid var(--border); }
  .modal-head h2 { font-size: 1.2rem; }
  .x { background: none; border: 0; color: var(--text-dim); font-size: 1.1rem; cursor: pointer; }
  .modal h3 { font-size: .8rem; text-transform: uppercase; letter-spacing: .06em;
    color: var(--text-dim); margin: var(--sp-4) 0 var(--sp-2); }
  .modal ul { margin: 0; padding-left: var(--sp-4); line-height: 1.6; }
  .modal li { margin-bottom: 4px; font-size: .92rem; }
  .verdict { background: var(--bg-card); border-left: 3px solid var(--accent);
    padding: var(--sp-3); border-radius: 8px; font-size: .95rem; line-height: 1.5; margin: 0; }
  .outlook { font-size: .92rem; line-height: 1.55; margin: var(--sp-3) 0 0; }
  .outlook :global(strong) { color: var(--text); font-weight: 600; }
  .verdict :global(strong) { font-weight: 600; }

  .bestlist { list-style: none; padding: 0; margin: var(--sp-2) 0 0; }
  .bestrow { display: flex; align-items: center; gap: var(--sp-3);
    padding: var(--sp-2) 0; border-bottom: 1px solid var(--border); }
  .bestrow:last-child { border-bottom: 0; }
  .bscore { width: 28px; height: 28px; border-radius: 8px; color: #04101f;
    font-weight: 700; font-size: .9rem; flex: 0 0 auto;
    display: inline-flex; align-items: center; justify-content: center; }
  .bmain { display: flex; flex-direction: column; flex: 1; min-width: 0; }
  .bspot { font-weight: 600; font-size: .92rem; }
  .bwhen { font-size: .78rem; color: var(--text-dim); }
  .bmeta { display: flex; flex-direction: column; align-items: flex-end; flex: 0 0 auto; }
  .bqual { font-size: .82rem; font-weight: 600; }
  .bsize { font-size: .78rem; color: var(--text-dim); }
  @media (min-width: 640px) {
    .modal-bg { align-items: center; }
    .modal { border-radius: var(--radius); }
  }

  .legend { background: var(--bg-card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: var(--sp-3) var(--sp-4); margin-bottom: var(--sp-4); }
  .legend summary { cursor: pointer; font-weight: 500; color: var(--text-dim); }
  .legend p { line-height: 1.5; font-size: .88rem; margin: var(--sp-3) 0 0; }
  .legend .small { font-size: .8rem; }
  .scale { display: flex; flex-wrap: wrap; gap: var(--sp-2); margin-top: var(--sp-3); }
  .chip { display: inline-flex; align-items: center; gap: 5px; font-size: .78rem;
    background: var(--bg-elev); border: 1px solid var(--border); border-radius: 999px; padding: 3px 9px; }
  .chip .sw { width: 10px; height: 10px; border-radius: 3px; }
  .legend-list { margin: var(--sp-2) 0 0; padding-left: var(--sp-4); font-size: .86rem;
    line-height: 1.5; }
  .legend-list li { margin-bottom: var(--sp-2); }


  /* shared day column width, used by calbar + every SpotCard scroller */
  :global(:root) { --day-col: 84px; }

  .calbar { position: sticky; top: 0; z-index: 5; background: var(--bg);
    padding: var(--sp-3) var(--sp-4); margin-bottom: var(--sp-2);
    display: flex; }
  .calspacer { flex: 0 0 0; }
  .calscroll { display: flex; gap: var(--sp-3); overflow-x: auto;
    scrollbar-width: none; flex: 1; }
  .calscroll::-webkit-scrollbar { display: none; }
  .calday { flex: 0 0 var(--day-col); display: flex; flex-direction: column;
    align-items: center; }
  .dow { font-size: .82rem; text-transform: uppercase; letter-spacing: .04em;
    color: var(--text-dim); }
  .dnum { font-size: 1.35rem; font-weight: 600; }

  .county { font-size: .95rem; text-transform: uppercase; letter-spacing: .08em;
    color: var(--text-dim); margin: var(--sp-5) 0 var(--sp-3); }
  .err { background: var(--bg-card); border: 1px solid var(--r1); border-radius: var(--radius); padding: var(--sp-4); }
  button { margin-top: var(--sp-2); background: var(--accent); color: #04101f;
    border: 0; border-radius: 8px; padding: 8px 16px; font: inherit; font-weight: 600; }
  .buoys { margin-top: var(--sp-6); }
  .buoy-row { display: flex; gap: var(--sp-3); overflow-x: auto;
    -webkit-overflow-scrolling: touch; padding-bottom: 4px; }
  .buoy { flex: 0 0 auto; min-width: 96px; background: var(--bg-card);
    border: 1px solid var(--border); border-radius: var(--radius);
    padding: var(--sp-3); text-align: center; }
  .bt { font-size: .78rem; color: var(--text-dim); font-weight: 500; }
  .bh { font-size: 1.5rem; font-weight: 600; margin-top: 2px; }
  .bh span { font-size: .8rem; font-weight: 400; color: var(--text-dim); }
  .bmeta { font-size: .8rem; color: var(--text-dim); }
  .bwhen { font-size: .7rem; color: var(--text-dim); margin-top: 2px; }
  .accuracy { margin-top: var(--sp-6); }
  .acc-buoy { background: var(--bg-card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: var(--sp-3); margin-bottom: var(--sp-2); }
  .acc-label { font-size: .88rem; font-weight: 500; margin-bottom: var(--sp-2); }
  .acc-row { display: flex; align-items: center; gap: var(--sp-3); font-size: .85rem;
    padding: 3px 0; }
  .acc-row.best { color: var(--r4); font-weight: 600; }
  .acc-model { flex: 1; }
  .acc-mae, .acc-corr { color: var(--text-dim); }
  .acc-row.best .acc-mae, .acc-row.best .acc-corr { color: var(--r4); }
  .acc-tag { font-size: .68rem; background: color-mix(in srgb, var(--r4) 22%, transparent);
    color: var(--r4); padding: 1px 7px; border-radius: 999px; }
  .foot { font-size: .8rem; margin-top: var(--sp-6); line-height: 1.5; }
</style>
