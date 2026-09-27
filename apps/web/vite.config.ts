import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the React app runs on :5173 and forwards API calls to Django on :8000,
// so the browser sees one origin and the session cookie + CSRF work normally.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/django-admin': 'http://localhost:8000',
      '/static': 'http://localhost:8000',
    },
  },
})
