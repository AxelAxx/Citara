import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Dev proxy: /api → FastAPI on :8000. The API's CORS already allows the
    // :5173 origin, but the proxy keeps the front origin-agnostic — set
    // VITE_API_URL=/api to route through it (the client's default is the
    // direct localhost URL per API_CONTRACT.md).
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
