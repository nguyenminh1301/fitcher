import { describe, expect, it, vi } from "vitest";

import { createHttpFeedback } from "@/lib/api/http/feedback";

function client(status = 204, body: unknown = undefined) {
  const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
    void init;
    return status === 204 ? new Response(null, { status }) : Response.json(body, { status });
  });
  return { fetcher, feedback: createHttpFeedback(fetcher) };
}

describe("http feedback", () => {
  it("posts the rating and note to the web server's feedback route", async () => {
    const { fetcher, feedback } = client();

    await feedback.send({ trace_id: "t".repeat(32), rating: "like", note: "Clear" });

    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("/api/feedback");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({ trace_id: "t".repeat(32), rating: "like", note: "Clear" });
  });

  it("rejects when the api refuses the feedback", async () => {
    const { feedback } = client(404, { detail: "answer not found" });

    await expect(feedback.send({ trace_id: "theirs", rating: "dislike" })).rejects.toThrow("404: answer not found");
  });
});
