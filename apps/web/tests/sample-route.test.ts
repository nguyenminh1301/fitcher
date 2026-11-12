import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { GET } from "@/app/api/sample/[file]/route";

let packs: string;

beforeEach(() => {
  packs = mkdtempSync(join(tmpdir(), "packs-"));
  mkdirSync(join(packs, "shop", "sample_data"), { recursive: true });
  writeFileSync(join(packs, "shop", "sample_data", "console.json"), JSON.stringify({ pack: { name: "shop" } }));
  process.env.PACKS_DIR = packs;
  process.env.ACTIVE_PACK = "shop";
});

afterEach(() => {
  delete process.env.PACKS_DIR;
  delete process.env.ACTIVE_PACK;
});

const call = (file: string) => GET(new Request(`http://web/api/sample/${file}`), { params: Promise.resolve({ file }) });

describe("sample data route", () => {
  it("serves an allowed file of the active pack", async () => {
    const response = await call("console");

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ pack: { name: "shop" } });
  });

  it("is a 404 when the pack has no such sample file", async () => {
    const response = await call("scenarios");

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "sample_data_missing" });
  });

  it("refuses any other file name", async () => {
    expect((await call("../policies")).status).toBe(404);
    expect((await call("console.json")).status).toBe(404);
  });

  it("is a 404 when no pack is active", async () => {
    delete process.env.ACTIVE_PACK;

    expect((await call("console")).status).toBe(404);
  });
});
