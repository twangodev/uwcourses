import { defineConfig } from "@playwright/test";
// IDE-specific fontconfig paths can make Chromium measure every glyph as zero.
const browserEnv = Object.fromEntries(
  Object.entries(process.env).filter(
    ([key, value]) =>
      value !== undefined &&
      !["FONTCONFIG_FILE", "FONTCONFIG_PATH", "FONTCONFIG_SYSROOT"].includes(
        key,
      ),
  ),
) as Record<string, string>;
const preview = Boolean(process.env.TEST_PREVIEW || process.env.CI);
const port = Number(process.env.TEST_PORT || 4173);
const baseURL = `http://127.0.0.1:${port}`;
export default defineConfig({
  testDir: "web/tests/browser",
  // Local workerd serves every browser from one process; avoid saturating it.
  workers: preview ? 2 : undefined,
  globalSetup:
    preview && process.env.BROWSER_DB_PREPARED !== "1"
      ? "./web/tests/browser/setup.ts"
      : undefined,
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: { env: browserEnv },
  },
  webServer: {
    command: preview
      ? `bun run preview --ip 127.0.0.1 --port ${port} --persist-to .site/browser-state`
      : `bun run dev --host 127.0.0.1 --port ${port}`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
