import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  timeout: 60000,
  testDir: './tests', testMatch: 'decks.spec.ts', workers: 1, reporter: 'list',
  use: {
    ...devices['Desktop Chrome'], baseURL: 'http://127.0.0.1:8885', viewport: { width: 1440, height: 1100 },
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, args: ['--no-sandbox'] } : {},
  },
  webServer: [
    { command: 'cd .. && .venv/bin/python -m uvicorn backend.tests.deck_browser_fixture:app --host 127.0.0.1 --port 8884', url: 'http://127.0.0.1:8884/api/health', reuseExistingServer: false },
    { command: 'npm run dev -- --port 8885', url: 'http://127.0.0.1:8885', env: { MEMO_DEV_API: 'http://127.0.0.1:8884' }, reuseExistingServer: false },
  ],
})
