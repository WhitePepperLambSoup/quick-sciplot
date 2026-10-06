#!/usr/bin/env node
// Create the Tauri updater manifest (latest.json) for a GitHub release.
//
// Usage:
//   node scripts/make-latest-json.mjs <version> <installer-path> <download-url> [notes-file]
//
// <installer-path> is the signed NSIS installer produced by `tauri build`; its
// `.sig` file (created when TAURI_SIGNING_PRIVATE_KEY is set) must sit next to it.
// <download-url> is where the installer will be published on the release.
// Upload the resulting latest.json as a release asset so that
// releases/latest/download/latest.json resolves to it.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

const [version, installer, url, notesFile] = process.argv.slice(2);
if (!version || !installer || !url) {
  console.error("usage: node scripts/make-latest-json.mjs <version> <installer-path> <download-url> [notes-file]");
  process.exit(2);
}

let signature;
try {
  signature = readFileSync(`${installer}.sig`, "utf8").trim();
} catch (error) {
  console.error(`Missing signature ${installer}.sig – build with TAURI_SIGNING_PRIVATE_KEY set. (${error.message})`);
  process.exit(1);
}

const manifest = {
  version: version.replace(/^v/, ""),
  notes: notesFile ? readFileSync(notesFile, "utf8").trim() : `Quick SciPlot ${version}`,
  pub_date: new Date().toISOString(),
  platforms: {
    "windows-x86_64": { signature, url },
  },
};

const output = join(dirname(installer), "latest.json");
writeFileSync(output, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(output);
