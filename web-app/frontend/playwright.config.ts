import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testMatch: 'study.spec.ts',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:8881',
    trace: 'retain-on-failure',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] }
      : {},
  },
  projects: [{ name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1100 } } }],
  webServer: [
    {
      command: 'cd .. && .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8880',
      url: 'http://127.0.0.1:8880/api/health',
      env: { FLASHCARD_WEB_PROGRESS: '/tmp/memo-web-e2e-progress.json', FLASHCARD_WEB_IMPORT_DESKTOP: '0', FLASHCARD_WEB_AUTH: '0' },
      reuseExistingServer: false,
    },
    { command: 'npm run dev -- --port 8881', url: 'http://127.0.0.1:8881', env: { MEMO_DEV_API: 'http://127.0.0.1:8880' }, reuseExistingServer: false },
  ],
})
