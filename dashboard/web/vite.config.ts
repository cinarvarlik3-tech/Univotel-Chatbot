import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Build output lands in dashboard/dist, which FastAPI serves (see
// dashboard/api/static.py). dist/ is committed: Railway runs a Python-only
// buildpack and will not execute npm.
export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5174,
    // `npm run dev` proxies the API to a locally running uvicorn so the SPA can
    // be developed with hot reload against real data.
    proxy: {
      '/api/dashboard': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
});
