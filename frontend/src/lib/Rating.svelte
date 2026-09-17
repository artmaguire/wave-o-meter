<script>
  import { ratingColor, ratingBand, RATING_LABELS } from './format.js';
  // props: score (0-5|null), size ('sm'|'md'|'lg'), showLabel
  let { score = null, size = 'md', showLabel = true } = $props();

  const band = $derived(ratingBand(score));
  const label = $derived(band == null ? 'No data' : RATING_LABELS[band]);
  // Smaller, tidier pills. Score numeral no longer dominates the card.
  const dims = { sm: 30, md: 38, lg: 48 };
  const px = $derived(dims[size] ?? 38);
</script>

<div class="wrap">
  <div class="rating" style="background:{ratingColor(score)}; width:{px}px; height:{px}px; font-size:{px*0.4}px">
    {score == null ? '–' : Math.round(score)}
  </div>
  {#if showLabel}
    <span class="label" class:big={size === 'lg'}>{label}</span>
  {/if}
</div>

<style>
  .wrap { display: inline-flex; align-items: center; gap: var(--sp-2); }
  .label { font-weight: 500; font-size: .9rem; }
  .label.big { font-size: 1rem; }
</style>
