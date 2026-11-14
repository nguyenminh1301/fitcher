import { describe, expect, it, vi } from "vitest";

import { createHttpSources, SourceError } from "@/lib/api/http/sources";

function respond(body: unknown, status = 200) {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function client(answer: () => Response) {
  const fetcher = vi.fn(async (_url: string, _init?: RequestInit) => answer());
  return { fetcher, sources: createHttpSources(fetcher as unknown as typeof fetch) };
}

const CONNECTION = {
  kind: "postgres", host: "db.internal", port: 5432, database: "erp", schema_name: "public", user: "reader", password: "s3cret", tls_mode: "prefer",
} as const;

describe("http sources", () => {
  it("lists sources and tests a connection through the web server's /api/sources routes", async () => {
    const { fetcher, sources } = client(() => respond([]));

    await sources.list();
    await sources.test(CONNECTION);

    expect(fetcher.mock.calls[0][0]).toBe("/api/sources");
    expect(fetcher.mock.calls[1][0]).toBe("/api/sources/test");
    expect(fetcher.mock.calls[1][1]).toMatchObject({ method: "POST", body: JSON.stringify(CONNECTION) });
  });

  it("creates, edits and deletes a source with the confirmation in the query", async () => {
    const { fetcher, sources } = client(() => respond({}));

    await sources.create({ ...CONNECTION, name: "shop" });
    await sources.update("shop", { host: "db2" });
    const removed = createHttpSources(vi.fn(async () => respond(null, 204)) as unknown as typeof fetch);
    await removed.remove("shop", "shop");

    expect(fetcher.mock.calls.map((call) => [call[0], (call[1] as RequestInit).method])).toEqual([
      ["/api/sources", "POST"], ["/api/sources/shop", "PATCH"]]);
  });

  it("sends the confirmation of a deletion and encodes the source name", async () => {
    const fetcher = vi.fn(async () => respond(null, 204));
    await createHttpSources(fetcher as unknown as typeof fetch).remove("a b", "a b");

    expect(fetcher).toHaveBeenCalledWith("/api/sources/a%20b?confirm=a%20b", { method: "DELETE" });
  });

  it("reads and changes the tables, optionally refreshing the catalog", async () => {
    const { fetcher, sources } = client(() => respond([]));

    await sources.tables("shop");
    await sources.tables("shop", true);
    await sources.changeTables("shop", { tables: [{ name: "orders", selected: true, mode: "copy" }] });

    expect(fetcher.mock.calls.map((call) => call[0])).toEqual([
      "/api/sources/shop/tables", "/api/sources/shop/tables?refresh=true", "/api/sources/shop/tables"]);
    expect((fetcher.mock.calls[2][1] as RequestInit).method).toBe("PUT");
  });

  it("starts, cancels and lists syncs", async () => {
    const { fetcher, sources } = client(() => respond({}));

    await sources.sync("shop");
    await sources.cancel("shop");
    await sources.syncs("shop");

    expect(fetcher.mock.calls.map((call) => [call[0], (call[1] as RequestInit | undefined)?.method])).toEqual([
      ["/api/sources/shop/sync", "POST"], ["/api/sources/shop/sync/cancel", "POST"], ["/api/sources/shop/syncs", undefined]]);
  });

  it("uploads a file as multipart form data and loads it with the confirmed types", async () => {
    const { fetcher, sources } = client(() => respond({}));
    const file = new File(["a,b\n1,2\n"], "orders.csv", { type: "text/csv" });

    await sources.upload(file);
    await sources.loadFile("abc", { name: "orders", columns: [{ name: "a", type: "Int64" }] });

    const form = (fetcher.mock.calls[0][1] as RequestInit).body as FormData;
    expect(fetcher.mock.calls[0][0]).toBe("/api/sources/files");
    expect((form.get("file") as File).name).toBe("orders.csv");
    expect((fetcher.mock.calls[0][1] as RequestInit).headers).toBeUndefined();
    expect(fetcher.mock.calls[1][0]).toBe("/api/sources/files/abc/load");
  });

  it("reports a failed connection as its fixed reason, never as text", async () => {
    const { sources } = client(() => respond({ detail: { reason: "authentication" } }, 422));

    const failure = await sources.test(CONNECTION).catch((error) => error);

    expect(failure).toBeInstanceOf(SourceError);
    expect(failure.reason).toBe("authentication");
    expect(failure.status).toBe(422);
  });

  it("reports the marts that block a deletion", async () => {
    const { sources } = client(() => respond({ detail: { message: "the marts a read this source", marts: ["a"] } }, 409));

    const failure = await sources.remove("shop", "shop").catch((error) => error);

    expect(failure.marts).toEqual(["a"]);
    expect(failure.status).toBe(409);
  });

  it("keeps a text detail as the message", async () => {
    const { sources } = client(() => respond({ detail: "a source named 'shop' already exists" }, 409));

    const failure = await sources.create({ ...CONNECTION, name: "shop" }).catch((error) => error);

    expect(failure.message).toContain("already exists");
    expect(failure.reason).toBeUndefined();
  });
});
