import { defineConfig } from '@playwright/test';
import os from 'node:os';
import path from 'node:path';

const dataDir = path.join(os.tmpdir(), `relay-e2e-${process.pid}`);

export default defineConfig({
  timeout: 60_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure' },
  webServer: [
    {
      command: 'npm.cmd run dev',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: false,
      timeout: 120_000,
      cwd: path.dirname(__dirname),
    },
    {
      command: `${path.join('.venv', 'Scripts', 'relay.exe')} init --data-dir "${dataDir}"`,
      url: undefined,
      timeout: 60_000,
      cwd: path.join(__dirname, '..'),
    },
  ],
});
