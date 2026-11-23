import { defineConfig, devices } from "@playwright/test";
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';

// Playwright sets FORCE_COLOR for workers; avoid Node's conflicting-color warning.
delete process.env.NO_COLOR;
const storage = mkdtempSync(join(tmpdir(), 'bookgen-e2e-'));
const python = process.env.PYTHON ?? resolve('../..', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');

export default defineConfig({
  testDir: "./tests/e2e",
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:3007", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [{
    command: `"${python}" -m uvicorn bookgen.main:create_app --factory --host 127.0.0.1 --port 8007`,
    url: 'http://127.0.0.1:8007/openapi.json',
    reuseExistingServer: false,
    env: {
      PYTHONPATH: resolve('../../apps/api/src'),
      BOOKGEN__LLM__PROVIDER: 'mock',
      BOOKGEN__APP__SQLITE_URI: `sqlite:///${join(storage, 'sessions.db')}`,
      BOOKGEN__APP__STORAGE_ROOT: join(storage, 'assets'),
      BOOKGEN__APP__CORS_ORIGINS: '["http://127.0.0.1:3007"]',
      BOOKGEN__EXPORT__PRINT_ORIGIN: 'http://127.0.0.1:3007',
    },
  }, {
    command: "npm run dev -- --hostname 127.0.0.1 --port 3007",
    url: "http://127.0.0.1:3007",
    reuseExistingServer: false,
    env: { NEXT_PUBLIC_API_ORIGIN: 'http://127.0.0.1:8007' },
  }],
});
