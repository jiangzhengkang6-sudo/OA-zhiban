/**
 * OA 智能体系统 MVP - 前端构建配置。
 *
 * 配置 @ 别名指向 src，开发环境将 /api 代理到后端 FastAPI（默认 8000 端口）。
 */
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${process.env.OA_BACKEND_PORT || '8001'}`,
        changeOrigin: true,
      },
    },
  },
  build: {
    target: ['es2020', 'edge88', 'firefox78', 'chrome87', 'safari14'],
  },
})
