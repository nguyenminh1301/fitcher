import { describe, expect, it, vi } from "vitest";

import { createHttpSetup } from "@/lib/api/http/setup";

const STATUS = { mode: null, steps: [{ id: "mode", state: "pending" }], complete: false };

function client(status = 200, body: unknown = STATUS) {
  const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
    void init;
    return Response.json(body, { status });
  });
  return { fetcher, setup: createHttpSetup(fetcher) };
}

describe("http setup", () => {
  it("reads the status from the web server's setup route", async () => {
    const { fetcher, setup } = client();
    expect(await setup.status()).toEqual(STATUS);
    expect(fetcher.mock.calls[0][0]).toBe("/api/setup/status");
  });

  it("skips a step and completes the setup with posts", async () => {
    const { fetcher, setup } = client();
    await setup.skip("mode");
    await setup.complete();
    expect(fetcher.mock.calls.map(([url, init]) => [url, init?.method])).toEqual([
      ["/api/setup/steps/mode/skip", "POST"], ["/api/setup/complete", "POST"],
    ]);
  });

  it("rejects with the api's reason", async () => {
    const { setup } = client(409, { detail: "answer or skip these steps first: mode" });
    await expect(setup.complete()).rejects.toThrow("409: answer or skip");
  });
});
