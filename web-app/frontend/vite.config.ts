import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', ['VITE_', 'MEMO_'])
  return {
    plugins: [react()],
    base: env.VITE_MEMO_BASE || '/',
    server: {
      port: 5173,
      strictPort: true,
      proxy: { '/api': env.MEMO_DEV_API || 'http://127.0.0.1:8000' },
    },
  }
})
