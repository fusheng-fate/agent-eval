import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 独立 Web 应用（去桌面宿主）：base '/'，产物 dist/，不搬旧 fixSkillAssetUrls 插件。
// 开发时把 /api 代理到后端 :8000，避免跨域；生产由反代/同域提供。
export default defineConfig({
  base: '/',
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
