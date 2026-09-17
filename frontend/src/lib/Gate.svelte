<script>
  import { submitGateAnswer } from './api.js';
  // props: question, maxTries, initialLocked, initialRemaining, onpass
  let { question = 'Enter the password', maxTries = 3,
        locked = false, lockoutRemaining = 0, onpass } = $props();

  let answer = $state('');
  let error = $state(null);
  let triesLeft = $state(maxTries);
  let submitting = $state(false);
  let isLocked = $state(locked);
  let remaining = $state(lockoutRemaining);

  async function submit(e) {
    e.preventDefault();
    if (submitting || isLocked || !answer.trim()) return;
    submitting = true; error = null;
    try {
      const r = await submitGateAnswer(answer);
      if (r.ok) { onpass?.(); return; }
      if (r.locked) {
        isLocked = true; remaining = r.lockout_remaining_s ?? 0;
        error = null;
      } else {
        triesLeft = r.tries_remaining ?? 0;
        error = triesLeft > 0
          ? `Incorrect. ${triesLeft} ${triesLeft === 1 ? 'try' : 'tries'} left.`
          : 'Incorrect.';
      }
    } catch {
      error = 'Something went wrong. Try again.';
    } finally {
      submitting = false; answer = '';
    }
  }

  function fmtRemaining(s) {
    const m = Math.ceil(s / 60);
    return `${m} minute${m === 1 ? '' : 's'}`;
  }
</script>

<div class="gate">
  <div class="card">
    <div class="wave">🌊</div>
    <h1>Wave-o-meter</h1>
    {#if isLocked}
      <p class="locked">Too many attempts. Try again in about {fmtRemaining(remaining)}.</p>
    {:else}
      <p class="q">{question}</p>
      <form onsubmit={submit}>
        <input
          type="password"
          bind:value={answer}
          placeholder="Answer"
          autocomplete="off"
          autocapitalize="off"
          spellcheck="false"
          disabled={submitting}
          aria-label={question}
        />
        <button type="submit" disabled={submitting || !answer.trim()}>
          {submitting ? '…' : 'Enter'}
        </button>
      </form>
      {#if error}<p class="err">{error}</p>{/if}
    {/if}
  </div>
</div>

<style>
  .gate { min-height: 100vh; display: flex; align-items: center;
    justify-content: center; padding: var(--sp-4); }
  .card { width: 100%; max-width: 340px; text-align: center;
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: var(--sp-6) var(--sp-5); }
  .wave { font-size: 2.4rem; }
  h1 { font-size: 1.4rem; margin: var(--sp-2) 0 var(--sp-5); }
  .q { font-size: 1rem; margin: 0 0 var(--sp-4); color: var(--text); }
  form { display: flex; flex-direction: column; gap: var(--sp-3); }
  input { background: var(--bg-elev); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px 14px; font: inherit; color: var(--text);
    text-align: center; }
  input:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
  button { background: var(--accent); color: #04101f; border: 0;
    border-radius: 10px; padding: 12px; font: inherit; font-weight: 600;
    cursor: pointer; }
  button:disabled { opacity: .5; }
  .err { color: var(--r2); font-size: .88rem; margin: var(--sp-3) 0 0; }
  .locked { color: var(--r2); line-height: 1.5; }
</style>
