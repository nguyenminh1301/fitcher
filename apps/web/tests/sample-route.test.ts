import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({ headers: async () => new Headers({ host: "localhost:3000" }), cookies: async () => ({ get: () => undefined }) }));

import { GET } from "@/app/api/sample/[file]/route";

let meStatus = 200;

let packs: string;

beforeEach(() => {
  packs = mkdtempSync(join(tmpdir(), "packs-"));
  mkdirSync(join(packs, "shop", "sample_data"), { recursive: true });
  writeFileSync(join(packs, "shop", "sample_data", "console.json"), JSON.stringify({ pack: { name: "shop" } }));
  process.env.PACKS_DIR = packs;
  process.env.ACTIVE_PACK = "shop";
  meStatus = 200;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    expect(url).toMatch(/\/me$/);
    return new Response("{}", { status: meStatus });
  }));
});

afterEach(() => {
  delete process.env.PACKS_DIR;
  delete process.env.ACTIVE_PACK;
  vi.unstubAllGlobals();
});

const call = (file: string) => GET(new Request(`http://web/api/sample/${file}`), { params: Promise.resolve({ file }) });

describe("sample data route", () => {
  it("serves an allowed file of the active pack", async () => {
    const response = await call("console");

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ pack: { name: "shop" } });
  });

  it("answers no suggestions, not a 404, when the pack has no sample scenarios", async () => {
    const response = await call("scenarios");

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ suggestions: [], scenarios: [] });
  });

  it("is a 404 when the pack has no sample console", async () => {
    process.env.ACTIVE_PACK = "other";

    const response = await call("console");

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "sample_data_missing" });
  });

  it("refuses any other file name", async () => {
    expect((await call("../policies")).status).toBe(404);
    expect((await call("console.json")).status).toBe(404);
  });

  it("is a 404 for the console and no suggestions when no pack is active", async () => {
    delete process.env.ACTIVE_PACK;

    expect((await call("console")).status).toBe(404);
    expect(await (await call("scenarios")).json()).toEqual({ suggestions: [], scenarios: [] });
  });

  it("reads no pack file for a request the api refuses, such as one without the owner's session", async () => {
    meStatus = 401;
    const signedOut = await call("console");
    expect(signedOut.status).toBe(401);
    expect(await signedOut.json()).toEqual({ error: "signed_out" });

    meStatus = 403;
    expect((await call("console")).status).toBe(403);
    expect((await call("scenarios")).status).toBe(403);
  });
});
