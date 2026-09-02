import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    // The PCM capture worklet is small enough that Vite would inline it as a
    // `data:text/javascript` URL, and `AudioWorklet.addModule` does not fetch
    // those reliably across browsers — the voice call would fail at connect
    // time with nothing in the build to explain why. Everything else keeps the
    // default inlining.
    assetsInlineLimit: (filePath) => (filePath.endsWith('pcmWorklet.js') ? false : undefined),
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8081',
        changeOrigin: true,
      },
    },
  },
})
