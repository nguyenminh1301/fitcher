import { afterEach, describe, expect, it, vi } from "vitest";

import { readStored, writeStored } from "../lib/storage";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("browser storage helpers", () => {
  it("round-trips a value", () => {
    writeStored("fitcher.theme", "dark");
    expect(readStored("fitcher.theme")).toBe("dark");
  });

  it("survives a localStorage that throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    expect(() => writeStored("fitcher.theme", "dark")).not.toThrow();
    expect(readStored("fitcher.theme")).toBeNull();
  });
});
