import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev-сервер фронта на 3333, запросы /api уходят на демон (8888)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3333,
    proxy: {
      '/api': 'http://localhost:8888',
    },
  },
})
