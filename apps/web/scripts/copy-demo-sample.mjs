// Copy the active pack's hand-written sample data into public/sample/ for the demo build (DECISIONS §15).
// The demo has no api and is deployed from apps/web alone (a static host, the fitcher-demo image), where the
// repository's packs/ folder is not there at run time, so the two files are served as static assets.
// `npm run build` runs this first; outside the demo build (NEXT_PUBLIC_FITCHER_DEMO is not "1") it does nothing.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const PACK_NAME = /^[a-z][a-z0-9_]*$/;

/**
 * Copy console.json and scenarios.json of ``pack`` into ``outDir``. Returns the copied file names, or an empty
 * list when this is not the demo build. Without ``pack``, sample data copied in before (the fitcher-demo image
 * copies it on the runner, outside the build context) is kept. A demo build without a valid pack or its
 * console.json fails, so a deploy never goes live with empty pages.
 */
export function copyDemoSample({ demo, pack, packsDir, outDir }) {
  if (demo !== "1") return [];
  if (!pack && existsSync(join(outDir, "console.json"))) return [];
  if (!pack || !PACK_NAME.test(pack)) throw new Error(`the demo build needs ACTIVE_PACK set to a pack name, got "${pack ?? ""}"`);
  const source = join(packsDir, pack, "sample_data");
  if (!existsSync(join(source, "console.json"))) throw new Error(`no sample data at ${join(source, "console.json")}`);
  mkdirSync(outDir, { recursive: true });
  const copied = [];
  for (const file of ["console.json", "scenarios.json"]) {
    if (!existsSync(join(source, file))) continue;
    copyFileSync(join(source, file), join(outDir, file));
    copied.push(file);
  }
  return copied;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const web = join(dirname(fileURLToPath(import.meta.url)), "..");
  const copied = copyDemoSample({
    demo: process.env.NEXT_PUBLIC_FITCHER_DEMO,
    pack: process.env.ACTIVE_PACK,
    packsDir: process.env.PACKS_DIR ?? resolve(web, "..", "..", "packs"),
    outDir: join(web, "public", "sample"),
  });
  if (copied.length) console.log(`demo sample data: ${copied.join(", ")} of ${process.env.ACTIVE_PACK}`);
}
