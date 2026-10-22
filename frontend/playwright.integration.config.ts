import { defineConfig, devices } from '@playwright/test'

const database = 'oa_agent_test'
const backendEnvironment = {
  ENVIRONMENT: 'test',
  OA_BACKEND_PORT: '8002',
  ALLOW_TEST_DATABASE_RESET: 'true',
  DATABASE_URL: `postgresql+asyncpg://oa:oa@localhost:5433/${database}`,
  DATABASE_SYNC_URL: `postgresql+psycopg://oa:oa@localhost:5433/${database}`,
  CHECKPOINTER_URL: `postgresql://oa:oa@localhost:5433/${database}`,
  LLM_PROVIDER: 'mock',
  OA_PROVIDER: 'mock',
  AUTH_PROVIDER: 'mock',
  MOCK_STATE_FILE: 'data/verification/meeting-integration/mock_state.json',
  ATTACHMENT_STORAGE_DIR: 'data/verification/meeting-integration/attachments',
  KNOWLEDGE_STORAGE_DIR: 'data/verification/meeting-integration/knowledge',
  AUDIT_EXPORT_STORAGE_DIR: 'data/verification/meeting-integration/audit_exports',
}

export default defineConfig({
  testDir: './e2e',
  testMatch: 'p2-meeting-integration.spec.ts',
  timeout: 45_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['json', { outputFile: 'data/verification/meeting-integration/result.json' }]],
  use: {
    baseURL: 'http://127.0.0.1:5174',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    channel: 'msedge',
    ...devices['Desktop Chrome'],
  },
  webServer: [
    {
      command: 'python run.py',
      cwd: '../backend',
      env: backendEnvironment,
      url: 'http://127.0.0.1:8002/healthz',
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5174 --strictPort',
      cwd: '.',
      env: { OA_BACKEND_PORT: '8002' },
      url: 'http://127.0.0.1:5174/meetings',
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
