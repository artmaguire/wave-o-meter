<script>
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { getForecast, getSessions, addSession, deleteSession } from '$lib/api.js';
  import Rating from '$lib/Rating.svelte';
  import DayCard from '$lib/DayCard.svelte';
  import {
    ratingColor, dirArrow, fmtTime, fmtDayFull, fmtFt, fmtFtRange,
    CONF_LABEL, CONF_COLOR, mToFt
  } from '$lib/format.js';

  let data = $state(null);
  let error = $state(null);
  let loading = $state(true);
  let selDate = $state(null); // selected day (YYYY-MM-DD)

  const id = $derived($page.params.id);

  async function load() {
    loading = true; error = null;
    try {
      data = await getForecast(id);
      selDate = data.days?.[0]?.date ?? null; // default to today
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }
  onMount(load);

  // --- session log ---
  let logs = $state([]);
  let logDate = $state(new Date().toISOString().slice(0, 10));
  let logRating = $state(3);
  let logNotes = $state('');
  let logBusy = $state(false);
  async function loadLogs() {
    try { logs = (await getSessions(id)).sessions ?? []; } catch { logs = []; }
  }
  onMount(loadLogs);
  async function saveLog(e) {
    e.preventDefault();
    if (logBusy) return;
    logBusy = true;
    try {
      await addSession({ spot_id: id, date: logDate, rating: logRating, notes: logNotes });
      logNotes = '';
      await loadLogs();
    } catch (_) { /* ignore */ } finally { logBusy = false; }
  }
  async function removeLog(sid) {
    try { await deleteSession(sid); await loadLogs(); } catch (_) {}
  }
  function sunLabel(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  const spot = $derived(data?.spot);
  const days = $derived(data?.days ?? []);
  const selDay = $derived(days.find((d) => d.date === selDate) ?? null);
  // hours belonging to the selected day
  // Surfable daylight window only: 6am–11pm (no middle-of-the-night rows).
  const selHours = $derived(
    (data?.hours ?? []).filter((h) => {
      if (h.time.slice(0, 10) !== selDate || h.missing) return false;
      const hr = parseInt(h.time.slice(11, 13), 10); // local wall-clock hour
      return hr >= 6 && hr <= 23;
    })
  );
  const anyLongRange = $derived(selHours.some((h) => h.confidence === 'long_range'));
  const seaTemp = $derived.by(() => {
    const withTemp = selHours.filter((h) => h.sea_temp_c != null);
    if (!withTemp.length) return null;
    return withTemp[Math.floor(withTemp.length / 2)].sea_temp_c;
  });

  // Daylight window for the selected day (from sunrise/sunset), so we never
  // recommend a session in the dark.
  function hourNum(iso) { return parseInt(iso.slice(11, 13), 10); }
  const daylight = $derived.by(() => {
    if (!selDay?.sunrise || !selDay?.sunset) return null;
    return { rise: hourNum(selDay.sunrise), set: hourNum(selDay.sunset) };
  });
  function inDaylight(h) {
    if (!daylight) return true;
    const hr = hourNum(h.time);
    return hr >= daylight.rise && hr <= daylight.set;
  }

  function windowReason(h) {
    const b = h.breakdown ?? {};
    const bits = [];
    if (h.wind?.relation === 'offshore') bits.push('offshore wind grooming the faces');
    else if (h.wind?.relation === 'cross-shore') bits.push('manageable cross-shore wind');
    if ((b.swell_direction ?? 0) >= 0.9) bits.push(`swell straight from the ${h.swell.direction_compass}`);
    if ((b.tide ?? 0) >= 0.9) bits.push(`a favourable ${h.tide.state} tide`);
    if ((h.swell?.period_s ?? 0) >= 11) bits.push(`long-period groundswell (${h.swell.period_s}s)`);
    if ((b.clean ?? 0) >= 0.85 && h.components?.dominant === 'swell') bits.push('a clean sea');
    if (!bits.length) bits.push('the best mix of size, wind and tide');
    return bits.join(', ') + '.';
  }
  function windowLabel(startH, endH) {
    const a = fmtTime(startH.time);
    if (startH.time === endH.time) return a;
    const endHr = (hourNum(endH.time) + 1) % 24;
    return `${a}–${endHr % 12 || 12}${endHr >= 12 ? 'pm' : 'am'}`;
  }

  // Recommended surf windows that day. Any daylight hour that's Fair+ (>=3) is
  // worth flagging — so a decent day nearly always gets a window/best time.
  // Adjacent hours group into one window ONLY if they're genuinely similar
  // (within SIMILAR of each other AND both still Fair+); a real dip or a big
  // score change splits them, so distinct humps (e.g. morning + evening) show
  // as separate windows rather than one long blur.
  const WIN_ENTER = 3.0;    // Fair+ — worth surfing
  const SIMILAR = 0.6;      // adjacent hours within this group together
  const WORTH_SHOWING = 0.7; // secondary windows must be within this of the best
  const bestWindows = $derived.by(() => {
    const good = selHours.filter((h) => h.score != null && inDaylight(h));
    const windows = [];
    let run = [];
    const flush = () => {
      if (run.length) {
        const peak = run.reduce((a, b) => (b.score > a.score ? b : a));
        windows.push({ start: run[0], end: run[run.length - 1], peak,
                       label: windowLabel(run[0], run[run.length - 1]),
                       reason: windowReason(peak) });
      }
      run = [];
    };
    for (let i = 0; i < good.length; i++) {
      const h = good[i];
      if (h.score < WIN_ENTER) { flush(); continue; }
      const prev = run[run.length - 1];
      const consecutive = prev && hourNum(h.time) - hourNum(prev.time) === 1;
      const similar = prev && Math.abs(h.score - prev.score) <= SIMILAR;
      if (consecutive && similar) run.push(h);
      else { flush(); run = [h]; }
    }
    flush();
    // Strongest first, then prune noise: drop windows clearly worse than the
    // day's best (so one standout hour doesn't get flanked by weaker
    // "also" boxes), and show at most 3.
    windows.sort((a, b) => b.peak.score - a.peak.score);
    if (windows.length > 1) {
      const top = windows[0].peak.score;
      return windows
        .filter((w, i) => i === 0 || top - w.peak.score <= WORTH_SHOWING)
        .slice(0, 3);
    }
    return windows;
  });
  const windowTimes = $derived.by(() => {
    const set = new Set();
    for (const w of bestWindows) {
      for (const h of selHours) {
        const t = new Date(h.time).getTime();
        if (t >= new Date(w.start.time).getTime() &&
            t <= new Date(w.end.time).getTime()) set.add(h.time);
      }
    }
    return set;
  });
  const isBest = (h) => windowTimes.has(h.time);
</script>

<div class="container">
  <a class="back" href="/">← All spots</a>

  {#if loading}
    <p class="muted">Loading…</p>
  {:else if error}
    <p class="err">Couldn't load: {error} <button onclick={load}>Retry</button></p>
  {:else if data}
    <header>
      <div>
        <h1>{spot.name}</h1>
        <div class="tags">
          <span class="tag">{spot.county}</span>
          <span class="tag">{spot.break_type}</span>
          <span class="tag">{spot.skill}</span>
        </div>
      </div>
    </header>

    <!-- Surfline-style horizontal day scrubber -->
    <h2 class="sec">12-day forecast</h2>
    <div class="dayscroll" role="tablist" aria-label="Select a day">
      {#each days as day}
        <DayCard
          {day}
          full
          selected={day.date === selDate}
          onselect={(d) => selDate = d.date}
        />
      {/each}
    </div>

    {#if selDay}
      <div class="dayhead">
        <strong>{fmtDayFull(selDay.date)}</strong>
        <span class="muted">{fmtFtRange(selDay.height_min, selDay.height_max)} surf</span>
      </div>
      <!-- conditions strip: weather, wetsuit, daylight -->
      <div class="condstrip">
        {#if selDay.weather}<span class="cond">{selDay.weather}</span>{/if}
        {#if selDay.air_temp_c != null}<span class="cond">🌡 Air {Math.round(selDay.air_temp_c)}°C</span>{/if}
        {#if selDay.sea_temp_c != null}<span class="cond">🌊 Sea {Math.round(selDay.sea_temp_c)}°C</span>{/if}
        {#if selDay.wetsuit}<span class="cond">🤿 {selDay.wetsuit}</span>{/if}
        {#if selDay.sunrise}<span class="cond">🌅 {sunLabel(selDay.sunrise)}</span>{/if}
        {#if selDay.sunset}<span class="cond">🌇 {sunLabel(selDay.sunset)}</span>{/if}
        {#if selDay.uv != null}<span class="cond">☀ UV {Math.round(selDay.uv)}</span>{/if}
      </div>
      {#if anyLongRange}
        <p class="lr">Long-range outlook — a single model, treat as a rough trend.</p>
      {/if}

      <!-- hourly detail table (horizontally scrollable so nothing is cut off) -->
      <div class="table-scroll">
        <div class="table" role="table">
          <div class="thead" role="row">
            <span class="c-time">Time</span>
            <span class="c-surf">Surf</span>
            <span class="c-swell">Swell</span>
            <span class="c-power">Power</span>
            <span class="c-wind">Wind</span>
            <span class="c-sea">Sea</span>
            <span class="c-tide">Tide</span>
          </div>
          {#each selHours as h}
            <div class="trow" role="row" class:best={isBest(h)}>
              <span class="c-time">
                {#if isBest(h)}<span class="star" title="best time to surf">★</span>{/if}
                {fmtTime(h.time)}
              </span>
              <span class="c-surf">
                <span class="score" style="background:{ratingColor(h.score)}">{Math.round(h.score)}</span>
                <span class="hgt">{mToFt(h.swell.height_m).toFixed(1)}<span class="unit">ft</span></span>
              </span>
              <span class="c-swell">
                <span class="val">{h.swell.period_s}<span class="unit">s</span></span>
                <span class="arrow" style="transform:{dirArrow(h.swell.direction_deg)}">↑</span>
                <span class="sub">{h.swell.direction_compass}</span>
              </span>
              <span class="c-power">
                {#if h.power_label}
                  <span class="pw pw-{h.power_label}" title="{h.power_kw_m} kW/m">{h.power_label}</span>
                {:else}·{/if}
              </span>
              <span class="c-wind">
                <span class="val">{Math.round(h.wind.speed_ms)}<span class="unit">m/s</span></span>
                <span class="arrow" style="transform:{dirArrow(h.wind.direction_deg)}">↑</span>
                <span class="sub rel-{h.wind.relation}">{h.wind.direction_compass}</span>
              </span>
              <span class="c-sea">
                {#if h.components}
                  <span class="seatype seatype-{h.components.dominant}">
                    {h.components.dominant === 'swell' ? 'clean' : 'choppy'}
                  </span>
                {:else}·{/if}
              </span>
              <span class="c-tide tstate">{h.tide.state}</span>
            </div>
          {/each}
        </div>
      </div>
      {#if !selHours.length}
        <p class="muted empty">No hourly data for this day.</p>
      {/if}
      {#each bestWindows as w, wi}
        <div class="bestbox">
          <span class="star">★</span>
          <div>
            <strong>{wi === 0 ? 'Best' : 'Also'} {w.label}</strong> — {w.reason}
            {#if w.peak.components?.secondary}
              <div class="secswell muted">
                + secondary swell {mToFt(w.peak.components.secondary.height_m).toFixed(1)}ft
                {w.peak.components.secondary.period_s}s from {w.peak.components.secondary.dir_compass}
              </div>
            {/if}
          </div>
        </div>
      {/each}
    {/if}

    <!-- local knowledge -->
    <section class="knowledge">
      <h2>Local knowledge</h2>
      {#if spot.notes}<p>{spot.notes}</p>{/if}
      {#if spot.hazards}<p class="hazard">⚠ {spot.hazards}</p>{/if}
      <p class="muted small">Prefers {spot.tide_pref} tide.</p>
      {#if !spot.orientation_verified}
        <p class="muted small">Orientation data for this spot is provisional.</p>
      {/if}
    </section>

    {#if spot.links && (spot.links.surfline || spot.links.surf_forecast)}
      <section class="compare">
        <h2>Compare forecasts</h2>
        <div class="links">
          {#if spot.links.surfline}
            <a href={spot.links.surfline} target="_blank" rel="noopener noreferrer">
              Surfline ↗
            </a>
          {/if}
          {#if spot.links.surf_forecast}
            <a href={spot.links.surf_forecast} target="_blank" rel="noopener noreferrer">
              surf-forecast.com ↗
            </a>
          {/if}
        </div>
      </section>
    {/if}

    <!-- session log: your own observations (calibration foundation) -->
    <section class="log">
      <h2>Your sessions</h2>
      <form class="logform" onsubmit={saveLog}>
        <div class="logrow">
          <input type="date" bind:value={logDate} aria-label="Session date" />
          <select bind:value={logRating} aria-label="Your rating">
            <option value={0}>0 – No surf</option>
            <option value={1}>1 – Very poor</option>
            <option value={2}>2 – Poor</option>
            <option value={3}>3 – Fair</option>
            <option value={4}>4 – Good</option>
            <option value={5}>5 – Very good</option>
          </select>
        </div>
        <input class="notes" type="text" bind:value={logNotes}
          placeholder="Notes (tide, crowd, how it broke…)" maxlength="500" />
        <button type="submit" disabled={logBusy}>{logBusy ? 'Saving…' : 'Log session'}</button>
      </form>

      {#if logs.length}
        <ul class="loglist">
          {#each logs as l}
            <li>
              <span class="lscore" style="background:{ratingColor(l.rating)}">{l.rating}</span>
              <span class="ldate">{l.date}</span>
              {#if l.notes}<span class="lnotes">{l.notes}</span>{/if}
              <button class="ldel" onclick={() => removeLog(l.id)} aria-label="Delete">✕</button>
            </li>
          {/each}
        </ul>
        <p class="muted small">Logging what you actually see builds the data to tune
          these forecasts to your spots over time.</p>
      {:else}
        <p class="muted small">No sessions logged yet. After you surf, log what it
          was really like — over time this tunes the forecast to your spots.</p>
      {/if}
    </section>

    <p class="foot muted">
      Forecasts open-ocean conditions, not the exact breaking wave on the bank.
      A strong guide, not a guarantee.
    </p>
  {/if}
</div>

<style>
  .back { display: inline-block; color: var(--text-dim); margin: var(--sp-3) 0; }
  .compare { margin-top: var(--sp-4); }
  .compare h2 { font-size: 1rem; margin-bottom: var(--sp-3); }
  .compare .links { display: flex; gap: var(--sp-3); flex-wrap: wrap; }
  .compare a { background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 999px; padding: 9px 16px; font-size: .9rem; font-weight: 500;
    color: var(--accent); }
  header { margin-bottom: var(--sp-4); }
  h1 { font-size: 1.5rem; }
  .tags { display: flex; gap: var(--sp-2); margin-top: var(--sp-2); flex-wrap: wrap; }
  .tag { font-size: .72rem; text-transform: capitalize; background: var(--bg-elev);
    color: var(--text-dim); padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border); }

  .sec { font-size: .95rem; text-transform: uppercase; letter-spacing: .06em;
    color: var(--text-dim); margin: var(--sp-4) 0 var(--sp-3); }

  .dayscroll { display: flex; gap: var(--sp-2); overflow-x: auto;
    -webkit-overflow-scrolling: touch; padding-bottom: var(--sp-2); }

  .dayhead { display: flex; align-items: baseline; gap: var(--sp-3);
    margin: var(--sp-5) 0 var(--sp-3); font-size: 1.1rem; }
  .lr { font-size: .82rem; color: var(--text-dim); margin: 0 0 var(--sp-3); }

  /* hourly table — horizontally scrollable so columns keep their size on mobile
     instead of compressing/cutting off the tide column */
  .table-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch;
    border: 1px solid var(--border); border-radius: var(--radius); }
  .table { background: var(--bg-card); min-width: 620px; }
  .thead, .trow { display: grid;
    grid-template-columns: 4.2rem 4.8rem 5rem 4.6rem 5.4rem 3.2rem 3.2rem;
    align-items: center; column-gap: var(--sp-3);
    padding: var(--sp-3) var(--sp-4); }
  .thead { font-size: .7rem; text-transform: uppercase; letter-spacing: .06em;
    color: var(--text-dim); border-bottom: 1px solid var(--border); }
  /* every header label same size/weight (Surf was visually smaller before) */
  .thead span { font-size: .7rem; font-weight: 600; }
  .trow { border-bottom: 1px solid var(--border); }
  .trow:last-child { border-bottom: 0; }

  /* best hour: highlighted row */
  .trow.best { background: color-mix(in srgb, var(--r5) 14%, transparent);
    box-shadow: inset 3px 0 0 var(--r5); }
  .star { color: var(--r5); font-size: .8rem; margin-right: 3px; }

  .c-time { color: var(--text-dim); font-size: .85rem; white-space: nowrap; }

  /* Surf cell: score chip + height */
  .c-surf { display: flex; align-items: center; gap: var(--sp-2); }
  .score { width: 30px; height: 30px; border-radius: 8px; color: #04101f;
    font-weight: 700; font-size: 1rem; flex: 0 0 auto;
    display: inline-flex; align-items: center; justify-content: center; }
  .hgt { font-weight: 600; font-size: .95rem; white-space: nowrap; }

  /* Swell + wind: value with a small trailing unit, arrow, compass */
  .c-swell, .c-wind { display: flex; align-items: center; gap: 5px; font-size: .88rem; white-space: nowrap; }
  .val { font-weight: 600; white-space: nowrap; }
  .unit { font-weight: 400; color: var(--text-dim); font-size: .72rem; margin-left: 1px; }
  .arrow { display: inline-block; color: var(--text-dim); font-size: .9rem; }
  .sub { color: var(--text-dim); font-size: .8rem; }
  .rel-offshore { color: var(--r4); } .rel-onshore { color: var(--r2); }
  .rel-cross-shore { color: var(--r3); }
  .c-tide { text-transform: capitalize; font-size: .85rem; color: var(--text-dim); }
  .c-sea { font-size: .8rem; }
  .c-power { font-size: .8rem; }
  .pw { padding: 2px 6px; border-radius: 999px; font-size: .72rem; font-weight: 600;
    white-space: nowrap; }
  .pw-gentle { background: color-mix(in srgb, var(--text-dim) 22%, transparent); color: var(--text-dim); }
  .pw-moderate { background: color-mix(in srgb, var(--r3) 22%, transparent); color: var(--r3); }
  .pw-punchy { background: color-mix(in srgb, var(--r4) 22%, transparent); color: var(--r4); }
  .pw-powerful { background: color-mix(in srgb, var(--r5) 24%, transparent); color: var(--r5); }
  .pw-heavy { background: color-mix(in srgb, var(--r1) 24%, transparent); color: var(--r1); }
  .seahint { font-size: .76rem; margin-top: var(--sp-2); line-height: 1.4; }
  .seatype { padding: 2px 7px; border-radius: 999px; font-size: .74rem; font-weight: 600; }
  .seatype-swell { background: color-mix(in srgb, var(--r4) 22%, transparent); color: var(--r4); }
  .seatype-windsea { background: color-mix(in srgb, var(--r2) 22%, transparent); color: var(--r2); }
  .seatemp { font-size: .85rem; color: var(--text-dim); margin-left: auto; }
  .empty { padding: var(--sp-4); }
  .bestbox { display: flex; gap: var(--sp-2); align-items: flex-start;
    margin-top: var(--sp-3); padding: var(--sp-3);
    background: color-mix(in srgb, var(--r5) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--r5) 40%, transparent);
    border-radius: var(--radius); font-size: .88rem; line-height: 1.45; }
  .bestbox .star { color: var(--r5); font-size: 1rem; }
  .secswell { font-size: .8rem; margin-top: 3px; }

  .knowledge { margin-top: var(--sp-6); background: var(--bg-card);
    border: 1px solid var(--border); border-radius: var(--radius); padding: var(--sp-4); }
  .knowledge h2 { font-size: 1rem; margin-bottom: var(--sp-2); }
  .knowledge p { margin: var(--sp-2) 0 0; line-height: 1.5; }
  .hazard { color: var(--r2); }
  .small { font-size: .78rem; }
  .foot { font-size: .8rem; margin-top: var(--sp-5); line-height: 1.5; }
  .err { color: var(--r1); }

  .condstrip { display: flex; flex-wrap: wrap; gap: var(--sp-2); margin: 0 0 var(--sp-3); }
  .cond { font-size: .8rem; background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 999px; padding: 4px 10px; color: var(--text-dim); }

  .log { margin-top: var(--sp-6); background: var(--bg-card);
    border: 1px solid var(--border); border-radius: var(--radius); padding: var(--sp-4); }
  .log h2 { font-size: 1rem; margin-bottom: var(--sp-3); }
  .logform { display: flex; flex-direction: column; gap: var(--sp-2); }
  .logrow { display: flex; gap: var(--sp-2); }
  .logform input, .logform select { flex: 1; min-width: 0; background: var(--bg-elev);
    border: 1px solid var(--border); border-radius: 8px; padding: 9px 10px;
    font: inherit; color: var(--text); }
  .logform button { background: var(--accent); color: #04101f; border: 0;
    border-radius: 8px; padding: 10px; font: inherit; font-weight: 600; cursor: pointer; }
  .logform button:disabled { opacity: .5; }
  .loglist { list-style: none; padding: 0; margin: var(--sp-4) 0 var(--sp-2); }
  .loglist li { display: flex; align-items: center; gap: var(--sp-2);
    padding: var(--sp-2) 0; border-bottom: 1px solid var(--border); }
  .lscore { width: 24px; height: 24px; border-radius: 6px; color: #04101f;
    font-weight: 700; font-size: .82rem; display: inline-flex; align-items: center;
    justify-content: center; flex: 0 0 auto; }
  .ldate { font-size: .82rem; color: var(--text-dim); flex: 0 0 auto; }
  .lnotes { font-size: .85rem; flex: 1; min-width: 0; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; }
  .ldel { background: none; border: 0; color: var(--text-dim); cursor: pointer;
    font-size: .9rem; flex: 0 0 auto; }
</style>
