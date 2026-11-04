import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-static';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [
    tailwindcss(),
    sveltekit({
      adapter: adapter({ pages: '../src/varde_runner/web/static/ui', assets: '../src/varde_runner/web/static/ui', fallback: 'spa-fallback.html' }),
      prerender: { entries: ['/', '/settings', '/settings/harnesses', '/settings/runner', '/settings/model-types', '/settings/display', '/settings/review', '/settings/status', '/_catalog'] }
    })
  ]
});
