import { describe, expect, it, vi } from "vitest";

import { createHttpModels } from "@/lib/api/http/models";

function client(status = 200, body: unknown = {}) {
  const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
    void init;
    return Response.json(body, { status });
  });
  return { fetcher, models: createHttpModels(fetcher) };
}

describe("http models", () => {
  it("reads the tiers from the web server's admin models route", async () => {
    const { fetcher, models } = client(200, { pack: "shop", tiers: [] });

    expect(await models.list()).toEqual({ pack: "shop", tiers: [] });
    expect(fetcher.mock.calls[0][0]).toBe("/api/admin/models");
  });

  it("puts the chosen alias of one tier", async () => {
    const { fetcher, models } = client(200, { tier: "sql-small", alias: "anthropic-small" });

    await models.set("sql-small", "anthropic-small");

    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("/api/admin/models/sql-small");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(init?.body as string)).toEqual({ alias: "anthropic-small" });
  });

  it("rejects with the api's reason when an alias is not eligible", async () => {
    const { models } = client(409, { detail: "gemini-small is not eligible for sql-small: no eval report ran sql-small with gemini-small" });

    await expect(models.set("sql-small", "gemini-small")).rejects.toThrow("409: gemini-small is not eligible");
  });
});
