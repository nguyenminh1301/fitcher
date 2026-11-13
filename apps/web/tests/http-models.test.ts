import { describe, expect, it, vi } from "vitest";

import { createHttpModels } from "@/lib/api/http/models";

function client(status = 200, body: unknown = {}) {
  const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
    void init;
    return status === 204 ? new Response(null, { status }) : Response.json(body, { status });
  });
  return { fetcher, models: createHttpModels(fetcher) };
}

describe("http models", () => {
  it("lists providers and tiers through the web server's routes", async () => {
    const { fetcher, models } = client(200, []);

    await models.providers();
    await models.tiers();

    expect(fetcher.mock.calls.map((call) => call[0])).toEqual(["/api/providers", "/api/models/tiers"]);
  });

  it("posts a new provider with its key once", async () => {
    const { fetcher, models } = client(201, { id: "openai", key_last4: "7777" });

    await models.addProvider({ kind: "openai", api_key: "sk-test-7777" });

    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("/api/providers");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({ kind: "openai", api_key: "sk-test-7777" });
  });

  it("maps a tier to a provider's model", async () => {
    const { fetcher, models } = client(200, { tier: "sql-gen" });

    await models.setTier("sql-gen", { provider_id: "openai", model: "gpt-5.5" });

    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("/api/models/tiers/sql-gen");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(init?.body as string)).toEqual({ provider_id: "openai", model: "gpt-5.5" });
  });

  it("tests a provider with an empty body unless a model is named", async () => {
    const { fetcher, models } = client(200, {});

    await models.testProvider("lab");
    await models.testProvider("lab", "qwen");

    expect(fetcher.mock.calls[0][0]).toBe("/api/providers/lab/test");
    expect(JSON.parse(fetcher.mock.calls[0][1]?.body as string)).toEqual({});
    expect(JSON.parse(fetcher.mock.calls[1][1]?.body as string)).toEqual({ model: "qwen" });
  });

  it("turns the classifier on with POST and off with DELETE", async () => {
    const { fetcher, models } = client(200, { enabled: true });

    await models.setClassifier(true);
    await models.setClassifier(false);

    expect(fetcher.mock.calls.map((call) => [call[0], call[1]?.method])).toEqual([
      ["/api/screening/classifier", "POST"], ["/api/screening/classifier", "DELETE"],
    ]);
  });

  it("removes a provider", async () => {
    const { fetcher, models } = client(204);

    await models.removeProvider("gemini");

    expect(fetcher.mock.calls[0]).toEqual(["/api/providers/gemini", { method: "DELETE" }]);
  });

  it("rejects with the api's reason", async () => {
    const { models } = client(409, { detail: "OpenAI is in use by a model tier or the embedding; map them elsewhere first" });

    await expect(models.removeProvider("openai")).rejects.toThrow("409: OpenAI is in use");
  });
});
