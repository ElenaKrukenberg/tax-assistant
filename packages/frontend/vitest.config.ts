import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Vitest rather than Jest: this is an ESM package ("type": "module") with ESM-only
// dependencies (react-markdown, remark-gfm), which Jest needs transform plumbing to
// load at all. next/jest exists, but nothing here depends on the Next compiler —
// the tests exercise the client component and the pure modules under src/lib.
export default defineConfig({
  plugins: [react()],
  resolve: {
    // Mirrors the `paths` in tsconfig.json. vite-tsconfig-paths would read them
    // directly, but two aliases are cheaper than another plugin in the chain.
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "@tax-assistant/shared": fileURLToPath(new URL("../shared", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    // Globals stay off: every test file imports describe/it/expect explicitly, so
    // eslint needs no extra environment and the imports say where they come from.
    globals: false,
    restoreMocks: true,
  },
});
