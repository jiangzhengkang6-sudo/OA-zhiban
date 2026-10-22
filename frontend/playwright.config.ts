import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testIgnore: ['**/p2-meeting-integration.spec.ts', '**/p2-drafting-integration.spec.ts', '**/p3-integration.spec.ts', '**/m1-identity.spec.ts', '**/m2-manual-oa.spec.ts', '**/m3-business.spec.ts'],
  timeout: 30_000,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['json', { outputFile: 'data/verification/b8-browser/result.json' }]],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    channel: 'msedge',
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: true,
    timeout: 30_000,
  },
})
