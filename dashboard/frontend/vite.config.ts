import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/dashboard/',
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8400',
      '/ws': { target: 'ws://localhost:8400', ws: true },
    },
  },
})
