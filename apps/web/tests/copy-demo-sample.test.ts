import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";

import { copyDemoSample } from "../scripts/copy-demo-sample.mjs";

let packsDir: string;
let outDir: string;

beforeEach(() => {
  const root = mkdtempSync(join(tmpdir(), "demo-sample-"));
  packsDir = join(root, "packs");
  outDir = join(root, "public", "sample");
  mkdirSync(join(packsDir, "shop", "sample_data"), { recursive: true });
  writeFileSync(join(packsDir, "shop", "sample_data", "console.json"), '{"pack":{"name":"shop"}}');
  writeFileSync(join(packsDir, "shop", "sample_data", "scenarios.json"), '{"suggestions":[]}');
});

describe("demo sample data copy", () => {
  it("copies both sample files of the active pack in the demo build", () => {
    expect(copyDemoSample({ demo: "1", pack: "shop", packsDir, outDir })).toEqual(["console.json", "scenarios.json"]);
    expect(readFileSync(join(outDir, "console.json"), "utf-8")).toBe('{"pack":{"name":"shop"}}');
  });

  it("does nothing outside the demo build", () => {
    expect(copyDemoSample({ demo: "0", pack: "shop", packsDir, outDir })).toEqual([]);
    expect(copyDemoSample({ demo: undefined, pack: undefined, packsDir, outDir })).toEqual([]);
    expect(existsSync(outDir)).toBe(false);
  });

  it("keeps sample data copied in before when no pack is named", () => {
    copyDemoSample({ demo: "1", pack: "shop", packsDir, outDir });

    expect(copyDemoSample({ demo: "1", pack: undefined, packsDir: join(packsDir, "gone"), outDir })).toEqual([]);
    expect(existsSync(join(outDir, "console.json"))).toBe(true);
  });

  it("fails a demo build without a pack or its sample data", () => {
    expect(() => copyDemoSample({ demo: "1", pack: undefined, packsDir, outDir })).toThrow(/ACTIVE_PACK/);
    expect(() => copyDemoSample({ demo: "1", pack: "../etc", packsDir, outDir })).toThrow(/ACTIVE_PACK/);
    expect(() => copyDemoSample({ demo: "1", pack: "missing", packsDir, outDir })).toThrow(/no sample data/);
  });
});
