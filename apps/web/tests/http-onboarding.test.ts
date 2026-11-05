import { describe, expect, it, vi } from "vitest";

import { createHttpDatasets } from "@/lib/api/http/datasets";
import { createHttpDocuments } from "@/lib/api/http/documents";
import { createHttpReview } from "@/lib/api/http/review";

function fetcher(status = 200, body: unknown = {}) {
  return vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
    void init;
    return status === 204 ? new Response(null, { status }) : Response.json(body, { status });
  });
}

describe("http datasets", () => {
  it("reads the compiled datasets", async () => {
    const fetch = fetcher(200, [{ id: "orders" }]);
    expect(await createHttpDatasets(fetch).list()).toEqual([{ id: "orders" }]);
    expect(fetch.mock.calls[0][0]).toBe("/api/datasets");
  });
});

describe("http review", () => {
  it("lists, edits, approves, test-runs and deletes items by their review id", async () => {
    const fetch = fetcher(200, { id: "metrics.gross_total" });
    const review = createHttpReview(fetch);

    await review.items();
    await review.update("metrics.gross_total", { body: "Net." });
    await review.approve("metrics.gross_total");
    expect(await review.testRun("metrics.gross_total")).toEqual({ id: "metrics.gross_total" });
    await review.remove("metrics.gross_total");

    const calls = fetch.mock.calls.map(([url, init]) => [url, init?.method ?? "GET"]);
    expect(calls).toEqual([
      ["/api/review/items", "GET"],
      ["/api/review/items/metrics.gross_total", "PATCH"],
      ["/api/review/items/metrics.gross_total/approve", "POST"],
      ["/api/review/items/metrics.gross_total/test-run", "POST"],
      ["/api/review/items/metrics.gross_total", "DELETE"],
    ]);
    expect(JSON.parse(fetch.mock.calls[1][1]?.body as string)).toEqual({ body: "Net." });
  });

  it("rejects with the api's reason when approval is refused", async () => {
    const review = createHttpReview(fetcher(422, { detail: "approve after a clean test-run" }));
    await expect(review.approve("metrics.x")).rejects.toThrow("422: approve after a clean test-run");
  });
});

describe("http documents", () => {
  it("uploads a multipart form with one allowed_roles field per role", async () => {
    const fetch = fetcher(201, { id: "d1", status: "indexed" });
    const file = new File(["# Notes"], "notes.md", { type: "text/markdown" });

    expect(await createHttpDocuments(fetch).upload(file, ["analyst", "sales"])).toEqual({ id: "d1", status: "indexed" });

    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("/api/documents");
    expect(init?.method).toBe("POST");
    const form = init?.body as FormData;
    expect((form.get("file") as File).name).toBe("notes.md");
    expect(form.getAll("allowed_roles")).toEqual(["analyst", "sales"]);
  });

  it("lists, retags, drafts from and deletes a document", async () => {
    const fetch = fetcher(200, { compiling: false, documents: [] });
    const documents = createHttpDocuments(fetch);

    expect(await documents.list()).toEqual({ compiling: false, documents: [] });
    await documents.setRoles("d1", ["analyst"]);
    await documents.draft("d1");
    await documents.remove("d1");

    expect(fetch.mock.calls.map(([url, init]) => [url, init?.method ?? "GET"])).toEqual([
      ["/api/documents", "GET"], ["/api/documents/d1", "PATCH"], ["/api/documents/d1/draft", "POST"], ["/api/documents/d1", "DELETE"],
    ]);
    expect(JSON.parse(fetch.mock.calls[1][1]?.body as string)).toEqual({ allowed_roles: ["analyst"] });
  });

  it("rejects a duplicate upload with the api's reason", async () => {
    const documents = createHttpDocuments(fetcher(409, { detail: "the same file is already registered as notes.md" }));
    await expect(documents.upload(new File(["x"], "copy.md"), ["analyst"])).rejects.toThrow("409: the same file");
  });
});
