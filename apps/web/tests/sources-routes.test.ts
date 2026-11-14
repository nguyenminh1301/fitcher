// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const forwardJson = vi.fn(async (_request: Request, path: string) => Response.json({ path }));
const forwardBody = vi.fn(async (_request: Request, path: string) => Response.json({ path }));
vi.mock("@/lib/server/api", () => ({ forwardJson, forwardBody }));

beforeEach(() => {
  forwardJson.mockClear();
  forwardBody.mockClear();
});

const params = (id: string) => ({ params: Promise.resolve({ id }) });

describe("source routes forward to the api", () => {
  it("lists, creates and tests", async () => {
    const root = await import("@/app/api/sources/route");
    const test = await import("@/app/api/sources/test/route");

    await root.GET(new Request("http://web/api/sources"));
    await root.POST(new Request("http://web/api/sources", { method: "POST", body: "{}" }));
    await test.POST(new Request("http://web/api/sources/test", { method: "POST", body: "{}" }));

    expect(forwardJson.mock.calls.map((call) => call[1])).toEqual(["/sources", "/sources", "/sources/test"]);
  });

  it("forwards one source with the confirmation of a deletion", async () => {
    const one = await import("@/app/api/sources/[id]/route");

    await one.PATCH(new Request("http://web/api/sources/shop", { method: "PATCH", body: "{}" }), params("shop"));
    await one.DELETE(new Request("http://web/api/sources/shop?confirm=shop", { method: "DELETE" }), params("shop"));

    expect(forwardJson.mock.calls.map((call) => call[1])).toEqual(["/sources/shop", "/sources/shop?confirm=shop"]);
  });

  it("forwards the tables with the refresh flag, the sync, its cancel and the history", async () => {
    const tables = await import("@/app/api/sources/[id]/tables/route");
    const sync = await import("@/app/api/sources/[id]/sync/route");
    const cancel = await import("@/app/api/sources/[id]/sync/cancel/route");
    const syncs = await import("@/app/api/sources/[id]/syncs/route");

    await tables.GET(new Request("http://web/api/sources/shop/tables?refresh=true"), params("shop"));
    await tables.PUT(new Request("http://web/api/sources/shop/tables", { method: "PUT", body: "{}" }), params("shop"));
    await sync.POST(new Request("http://web/api/sources/shop/sync", { method: "POST" }), params("shop"));
    await cancel.POST(new Request("http://web/api/sources/shop/sync/cancel", { method: "POST" }), params("shop"));
    await syncs.GET(new Request("http://web/api/sources/shop/syncs"), params("shop"));

    expect(forwardJson.mock.calls.map((call) => call[1])).toEqual([
      "/sources/shop/tables?refresh=true", "/sources/shop/tables", "/sources/shop/sync", "/sources/shop/sync/cancel",
      "/sources/shop/syncs"]);
  });

  it("forwards an uploaded file as it came, and the load of an upload as JSON", async () => {
    const files = await import("@/app/api/sources/files/route");
    const load = await import("@/app/api/sources/files/[id]/load/route");

    await files.POST(new Request("http://web/api/sources/files", { method: "POST", body: "x" }));
    await load.POST(new Request("http://web/api/sources/files/abc/load", { method: "POST", body: "{}" }), params("abc"));

    expect(forwardBody.mock.calls.map((call) => call[1])).toEqual(["/sources/files"]);
    expect(forwardJson.mock.calls.map((call) => call[1])).toEqual(["/sources/files/abc/load"]);
  });
});
