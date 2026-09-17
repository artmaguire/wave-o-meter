<script>
  import '../app.css';
  import { onMount } from 'svelte';
  import { getGateStatus } from '$lib/api.js';
  import Gate from '$lib/Gate.svelte';

  let { children } = $props();

  // Gate check: until we know the status, show nothing (avoids flashing the app
  // before the gate). If disabled or already authorised, render the app.
  let checked = $state(false);
  let gate = $state(null); // { enabled, authorised, question, locked, ... }

  async function check() {
    try {
      gate = await getGateStatus();
    } catch {
      // If the status call fails, fail closed only if we can't tell; but a
      // network error shouldn't lock a legit user out of a LAN app — treat as
      // "no gate" so the app still loads, the API 401s will guide if needed.
      gate = { enabled: false, authorised: true };
    } finally {
      checked = true;
    }
  }
  onMount(check);

  const needGate = $derived(gate && gate.enabled && !gate.authorised);
</script>

<svelte:head>
  <meta name="description" content="Personal surf forecast for Irish west-coast spots" />
</svelte:head>

{#if !checked}
  <!-- brief blank while we check the gate -->
{:else if needGate}
  <Gate
    question={gate.question}
    maxTries={gate.max_tries}
    locked={gate.locked}
    lockoutRemaining={gate.lockout_remaining_s}
    onpass={() => { gate = { ...gate, authorised: true }; }}
  />
{:else}
  {@render children()}
{/if}
