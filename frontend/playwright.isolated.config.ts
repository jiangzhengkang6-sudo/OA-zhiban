import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: ['p1-formalization.spec.ts', 'p2-meeting.spec.ts', 'm3-assistant.spec.ts'],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  outputDir: '../data/verification/toolchain/browser-output',
  reporter: [
    ['list'],
    ['json', { outputFile: '../data/verification/toolchain/browser-result.json' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:5196',
    channel: 'msedge',
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 960 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5196 --strictPort',
    env: { OA_BACKEND_PORT: '9' },
    url: 'http://127.0.0.1:5196/login',
    reuseExistingServer: false,
    timeout: 30_000,
  },
})
