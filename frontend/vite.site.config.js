import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig } from 'vite'

// The public, read-only site (see backend/app/publish.py). Built with relative
// paths: every published page sets <base href> to wherever the site is hosted.
export default defineConfig({
  plugins: [svelte()],
  base: './',
  build: {
    outDir: 'dist-site',
    rollupOptions: { input: 'site.html' },
  },
})
