import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    // During dev, proxy API calls to the FastAPI backend.
    proxy: {
      '/api': 'http://127.0.0.1:8080'
    }
  }
});
