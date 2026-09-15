#!/usr/bin/env node
// Fails if package-lock.json is missing any platform-specific optional dependency.
//
// Native packages (@tailwindcss/oxide, lightningcss, sharp, @next/swc, ...) ship one
// prebuilt binary per platform as optional dependencies. A lockfile that records only
// the entries for the machine it was generated on installs cleanly there and then fails
// at build time on Linux CI with "Cannot find native binding" — npm/cli#4828. A full
// `npm install` records every platform; incremental installs can drop them again, so
// this check guards the invariant.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const lockPath = join(repoRoot, "package-lock.json");

const PLATFORM_TOKEN =
  /(darwin|linux|linuxmusl|win32|freebsd|android|openharmony|wasm32|musl|gnu|gnueabihf|musleabihf|arm|arm64|x64|ia32|s390x|ppc64|riscv64|loong64)/;

const { packages } = JSON.parse(readFileSync(lockPath, "utf8"));

const missing = [];
for (const [parent, entry] of Object.entries(packages)) {
  for (const dep of Object.keys(entry.optionalDependencies ?? {})) {
    // Only platform binaries: a missing entry for one of these is a latent build failure,
    // whereas an ordinary optional dependency is genuinely optional.
    if (!PLATFORM_TOKEN.test(dep)) continue;
    const nested = `${parent}/node_modules/${dep}`;
    if (nested in packages || `node_modules/${dep}` in packages) continue;
    missing.push({ dep, parent: parent || "(root)" });
  }
}

if (missing.length === 0) {
  console.log("package-lock.json: all platform-specific optional dependencies recorded.");
  process.exit(0);
}

console.error(
  `package-lock.json is missing ${missing.length} platform-specific ` +
    `optional dependenc${missing.length === 1 ? "y" : "ies"}:\n`,
);
for (const { dep, parent } of missing) {
  console.error(`  ${dep}  (optional dependency of ${parent})`);
}
console.error(
  "\nThese will fail at build time on any platform whose binary is absent.\n" +
    "Fix with a full regeneration, which records every platform:\n" +
    "\n  rm -rf node_modules package-lock.json && npm install\n",
);
process.exit(1);