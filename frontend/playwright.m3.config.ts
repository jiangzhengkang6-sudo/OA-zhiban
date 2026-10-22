import { defineConfig } from '@playwright/test'

const backendPython = '..\\backend\\.venv\\Scripts\\python.exe'

export default defineConfig({
  testDir: './e2e',
  testMatch: 'm3-business.spec.ts',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  outputDir: '../data/verification/m3/browser-output',
  reporter: [['list'], ['json', { outputFile: '../data/verification/m3/browser-result.json' }]],
  use: {
    baseURL: 'http://127.0.0.1:5195',
    channel: 'msedge',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 960 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: [
    {
      command: `${backendPython} ..\\backend\\scripts\\m3_preview.py`,
      cwd: '.',
      url: 'http://127.0.0.1:8015/healthz',
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5195 --strictPort',
      cwd: '.',
      env: { OA_BACKEND_PORT: '8015' },
      url: 'http://127.0.0.1:5195/login',
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})