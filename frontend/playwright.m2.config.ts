import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './e2e', testMatch: 'm2-manual-oa.spec.ts', fullyParallel: false, workers: 1, timeout: 60_000,
  reporter: [['list'], ['json', { outputFile: '../data/verification/m2/browser-result.json' }]],
  use: { baseURL: 'http://127.0.0.1:5194', channel: 'msedge', ...devices['Desktop Chrome'], trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  outputDir: '../data/verification/m2/browser-output',
})
