/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Keep in sync with docs/windows_packaging.md browser minimums.
  // Vite 8 baseline-widely-available == chrome111 / edge111 / firefox114.
  build: {
    target: ['chrome111', 'edge111', 'firefox114'],
  },
  server: {
    port: 4567,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 4567,
    strictPort: true,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
})