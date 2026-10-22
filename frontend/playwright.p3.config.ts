import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: ['p3-integration.spec.ts', 'p2-drafting-integration.spec.ts', 'p2-meeting-integration.spec.ts', 'p1-formalization.spec.ts', 'p2-meeting.spec.ts'],
  timeout: 60_000, workers: 1, fullyParallel: false, retries: 0,
  outputDir: 'data/verification/p3/browser',
  reporter: [['list'], ['json', { outputFile: 'data/verification/p3/result.json' }]],
  use: { baseURL: 'http://127.0.0.1:5182', channel: 'msedge', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 960 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
})
