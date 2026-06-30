import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// IMPORTANT: base must match your GitHub repo name for GitHub Pages
// e.g. if your repo is github.com/kcrha/system-flow-story, base is '/system-flow-story/'
// If you set up a custom domain instead, change base back to '/'
export default defineConfig({
  plugins: [svelte()],
  base: '/system-flow-story/',
  build: {
    outDir: 'dist'
  }
});
