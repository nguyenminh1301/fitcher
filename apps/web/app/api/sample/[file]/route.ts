// The active pack's sample data for the sample-data mode (DECISIONS §15): only console.json and
// scenarios.json of packs/<ACTIVE_PACK>/sample_data are served; anything else is a 404.

import { readFile } from "node:fs/promises";
import { join, resolve } from "node:path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const FILES = new Set(["console", "scenarios"]);
const PACK_NAME = /^[a-z][a-z0-9_]*$/;

function missing(): Response {
  return Response.json({ error: "sample_data_missing" }, { status: 404 });
}

export async function GET(_request: Request, { params }: { params: Promise<{ file: string }> }): Promise<Response> {
  const { file } = await params;
  const pack = process.env.ACTIVE_PACK ?? "";
  if (!FILES.has(file) || !PACK_NAME.test(pack)) return missing();
  // `npm run dev` runs in apps/web; Compose mounts the packs and sets PACKS_DIR.
  const packs = process.env.PACKS_DIR ?? resolve(process.cwd(), "..", "..", "packs");
  try {
    const text = await readFile(join(packs, pack, "sample_data", `${file}.json`), "utf-8");
    return new Response(text, { headers: { "content-type": "application/json", "cache-control": "no-store" } });
  } catch {
    return missing();
  }
}
