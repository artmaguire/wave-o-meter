<script>
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { getSpots, getSessionOptions, addSession } from '$lib/api.js';
  import { RATING_LABELS, ratingColor } from '$lib/format.js';

  let spots = $state([]);
  let options = $state(null);
  let loading = $state(true);
  let saving = $state(false);
  let saved = $state(false);
  let error = $state(null);

  // form state — spot can be pre-selected via ?spot=<id>
  let form = $state({
    spot_id: '',
    date: new Date().toISOString().slice(0, 10),
    time_of_day: '',
    rating: 3,
    wave_size: '',
    wave_quality: '',
    wind: '',
    tide: '',
    tide_movement: '',
    crowd: '',
    board: '',
    wetsuit: '',
    length: '',
    notes: ''
  });

  onMount(async () => {
    try {
      const [s, o] = await Promise.all([getSpots(), getSessionOptions()]);
      spots = s.spots ?? [];
      options = o.options ?? {};
      const pre = $page.url.searchParams.get('spot');
      form.spot_id = pre && spots.some((x) => x.id === pre) ? pre : (spots[0]?.id ?? '');
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  });

  // Where we came from: /log?spot=<id> should return to that spot, not the list.
  const fromSpot = $derived($page.url.searchParams.get('spot') ?? '');
  const fromSpotName = $derived(
    spots.find((s) => s.id === fromSpot)?.name ?? 'Back'
  );

  // group spots by county for the picker
  const byCounty = $derived.by(() => {
    const m = new Map();
    for (const s of spots) {
      if (!m.has(s.county)) m.set(s.county, []);
      m.get(s.county).push(s);
    }
    return [...m.entries()];
  });

  async function submit(e) {
    e.preventDefault();
    if (saving || !form.spot_id) return;
    saving = true; error = null;
    try {
      await addSession({ ...form, rating: Number(form.rating) });
      saved = true;
      // reset the observation fields, keep spot/date for a quick second entry
      form = { ...form, time_of_day: '', wave_size: '', wave_quality: '',
               wind: '', tide: '', tide_movement: '', crowd: '', board: '',
               wetsuit: '', length: '', notes: '' };
      setTimeout(() => (saved = false), 3000);
    } catch (e2) {
      error = 'Could not save — check the fields and try again.';
    } finally {
      saving = false;
    }
  }
</script>

<div class="container">
  {#if fromSpot}
    <a class="back" href="/spot/{fromSpot}">← {fromSpotName}</a>
  {:else}
    <a class="back" href="/">← All spots</a>
  {/if}
  <h1>Log a session</h1>
  <p class="muted intro">
    Record what you actually saw. Over time this is what lets the forecast be
    tuned to these spots — only the spot, date and your rating are required.
  </p>

  {#if loading}
    <p class="muted">Loading…</p>
  {:else if error && !options}
    <p class="err">{error}</p>
  {:else}
    <form onsubmit={submit}>
      <!-- essentials -->
      <fieldset>
        <legend>The basics</legend>

        <label>
          <span>Spot</span>
          <select bind:value={form.spot_id} required>
            {#each byCounty as [county, list]}
              <optgroup label={county}>
                {#each list as s}<option value={s.id}>{s.name}</option>{/each}
              </optgroup>
            {/each}
          </select>
        </label>

        <div class="row">
          <label>
            <span>Date</span>
            <input type="date" bind:value={form.date} required />
          </label>
          <label>
            <span>Time out</span>
            <input type="time" bind:value={form.time_of_day} />
          </label>
        </div>

        <label>
          <span>Your rating</span>
          <select bind:value={form.rating} required>
            {#each RATING_LABELS as lbl, i}
              <option value={i}>{i} – {lbl}</option>
            {/each}
          </select>
          <span class="swatch" style="background:{ratingColor(Number(form.rating))}"></span>
        </label>
      </fieldset>

      <!-- what it was like -->
      <fieldset>
        <legend>What it was like</legend>
        <div class="row">
          <label>
            <span>Wave size</span>
            <select bind:value={form.wave_size}>
              <option value="">–</option>
              {#each options.wave_size as v}<option>{v}</option>{/each}
            </select>
          </label>
          <label>
            <span>Wave quality</span>
            <select bind:value={form.wave_quality}>
              <option value="">–</option>
              {#each options.wave_quality as v}<option>{v}</option>{/each}
            </select>
          </label>
        </div>
        <div class="row">
          <label>
            <span>Wind</span>
            <select bind:value={form.wind}>
              <option value="">–</option>
              {#each options.wind as v}<option>{v}</option>{/each}
            </select>
          </label>
          <label>
            <span>Crowd</span>
            <select bind:value={form.crowd}>
              <option value="">–</option>
              {#each options.crowd as v}<option>{v}</option>{/each}
            </select>
          </label>
        </div>
        <div class="row">
          <label>
            <span>Tide</span>
            <select bind:value={form.tide}>
              <option value="">–</option>
              {#each options.tide as v}<option>{v}</option>{/each}
            </select>
          </label>
          <label>
            <span>Tide moving</span>
            <select bind:value={form.tide_movement}>
              <option value="">–</option>
              {#each options.tide_movement as v}<option>{v}</option>{/each}
            </select>
          </label>
        </div>
      </fieldset>

      <!-- you -->
      <fieldset>
        <legend>Your session</legend>
        <div class="row">
          <label>
            <span>Board</span>
            <select bind:value={form.board}>
              <option value="">–</option>
              {#each options.board as v}<option>{v}</option>{/each}
            </select>
          </label>
          <label>
            <span>Wetsuit</span>
            <select bind:value={form.wetsuit}>
              <option value="">–</option>
              {#each options.wetsuit as v}<option>{v}</option>{/each}
            </select>
          </label>
        </div>
        <label>
          <span>Time in water</span>
          <select bind:value={form.length}>
            <option value="">–</option>
            {#each options.length as v}<option>{v}</option>{/each}
          </select>
        </label>
      </fieldset>

      <fieldset>
        <legend>Notes</legend>
        <textarea bind:value={form.notes} rows="3" maxlength="1000"
          placeholder="Anything the fields miss — which peak worked, how it changed, hazards…"></textarea>
      </fieldset>

      {#if error}<p class="err">{error}</p>{/if}
      <button type="submit" disabled={saving}>
        {saving ? 'Saving…' : 'Save session'}
      </button>
      {#if saved}<p class="ok">✓ Session logged</p>{/if}
    </form>
  {/if}
</div>

<style>
  .back { display: inline-block; color: var(--text-dim); margin: var(--sp-3) 0; }
  h1 { font-size: 1.5rem; }
  .intro { font-size: .88rem; line-height: 1.5; margin: var(--sp-2) 0 var(--sp-4); }

  fieldset { border: 1px solid var(--border); border-radius: var(--radius);
    padding: var(--sp-3) var(--sp-4) var(--sp-4); margin: 0 0 var(--sp-4); }
  legend { font-size: .74rem; text-transform: uppercase; letter-spacing: .06em;
    color: var(--text-dim); padding: 0 var(--sp-2); }

  label { display: flex; flex-direction: column; gap: 4px; margin-top: var(--sp-3);
    position: relative; }
  label > span { font-size: .8rem; color: var(--text-dim); }
  .row { display: flex; gap: var(--sp-3); }
  .row label { flex: 1; min-width: 0; }

  select, input, textarea { background: var(--bg-elev); border: 1px solid var(--border);
    border-radius: 8px; padding: 10px; font: inherit; color: var(--text); width: 100%; }
  textarea { resize: vertical; }
  .swatch { position: absolute; right: 10px; bottom: 12px; width: 14px; height: 14px;
    border-radius: 4px; pointer-events: none; }

  button { width: 100%; background: var(--accent); color: #04101f; border: 0;
    border-radius: 10px; padding: 13px; font: inherit; font-weight: 600;
    cursor: pointer; }
  button:disabled { opacity: .5; }
  .err { color: var(--r1); font-size: .88rem; }
  .ok { color: var(--r4); font-size: .9rem; text-align: center; margin-top: var(--sp-3); }
</style>
