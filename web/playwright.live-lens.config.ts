import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";

// Live Lens browser E2E — the one surface the Python audits couldn't reach: a
// REAL browser running the Brain-served camera page. It boots the Python Brain
// over plain http on 127.0.0.1 (a browser secure-context, so getUserMedia works
// without TLS), drives the page with a FAKE camera, and asserts the page's JS
// actually runs under the strict nonce CSP (a CSP regression that blocked the
// inline script would surface here as a console error — exactly what a Python
// unit test can't catch). Chrome-only (the fake-camera flags are Chromium's).
const DIR = path.join(os.tmpdir(), "dl-live-lens-e2e");

export default defineConfig({
  testDir: "./e2e",
  testMatch: "live-lens.spec.ts",
  timeout: 90_000,
  use: {
    baseURL: "http://127.0.0.1:7788",
    permissions: ["camera"],
    launchOptions: {
      // CI installs its own Chromium (`npx playwright install chromium`); the
      // dev sandbox pins the pre-installed one via PW_CHROMIUM.
      executablePath: process.env.PW_CHROMIUM || undefined,
      args: [
        "--use-fake-device-for-media-stream",   // a synthetic camera, no hardware
        "--use-fake-ui-for-media-stream",        // auto-accept the permission prompt
      ],
    },
  },
  webServer: {
    // The Brain serves /dreamlayer/live. Base deps (Pillow/numpy) are enough to
    // render the page; no TLS needed (loopback is a secure context).
    command:
      "python -m dreamlayer.ai_brain.server --host 127.0.0.1 --port 7788 --dir " + DIR,
    cwd: "../host-python",
    env: { PYTHONPATH: "src", DREAMLAYER_DIR: DIR },
    url: "http://127.0.0.1:7788/dreamlayer/live",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [{ name: "chromium-camera" }],
});
