<script>
  import '../app.css';
  let { children } = $props();
</script>

<svelte:head>
  <meta name="description" content="Personal surf forecast for Irish west-coast spots" />
</svelte:head>

{@render children()}
