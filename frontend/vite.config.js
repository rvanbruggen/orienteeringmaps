import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'

// In development the FastAPI backend runs on :8420 (see README).
const backend = 'http://127.0.0.1:8420'

export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      '/api': backend,
      '/media': backend,
      '/healthz': backend,
    },
  },
})
