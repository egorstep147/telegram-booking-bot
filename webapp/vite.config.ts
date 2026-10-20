import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// В разработке (npm run dev) запросы /api уходят на бэкенд shopbot на порту 8080
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8085' } },
})
