import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// The dev server proxies /api to the Python backend so the browser and the
// Tauri webview both talk to a same-origin URL and CORS never enters into it.
const BACKEND = process.env.GAIA_BACKEND_URL ?? 'http://127.0.0.1:8756'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
        // Streaming responses must not be buffered by the proxy.
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['cache-control'] = 'no-cache, no-transform'
          })
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    // Tauri loads these from the filesystem; relative paths keep that working.
    assetsDir: 'assets',
    sourcemap: false,
    target: 'es2022',
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
