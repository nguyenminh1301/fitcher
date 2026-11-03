import { describe, expect, it, vi } from "vitest";

import { createHttpChat } from "@/lib/api/http/chat";
import type { AskEvent } from "@/lib/api/events";
import { parseStream, type SseFrame } from "@/lib/sse/parseStream";

const encoder = new TextEncoder();

function stream(chunks: (string | Uint8Array)[], options: { error?: Error; signal?: AbortSignal } = {}): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk);
      if (options.signal) options.signal.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
      else if (options.error) controller.error(options.error);
      else controller.close();
    },
  });
}

async function frames(body: ReadableStream<Uint8Array>): Promise<SseFrame[]> {
  const out: SseFrame[] = [];
  for await (const frame of parseStream(body)) out.push(frame);
  return out;
}

const frame = (event: Record<string, unknown>) => `event: ${event.event}\ndata: ${JSON.stringify(event)}\n\n`;
const T = { trace_id: "t".repeat(32) };
const STATUS = { ...T, event: "status", node: "extract", phase: "start", attempt: null };
const DONE = { ...T, event: "done" };

describe("parseStream", () => {
  it("reads named frames and skips comments", async () => {
    expect(await frames(stream([": keep-alive\n\n", "event: status\ndata: {\"a\":1}\n\n"]))).toEqual([{ event: "status", data: "{\"a\":1}" }]);
  });

  it("joins data lines, accepts CRLF and frames split across chunks", async () => {
    const parsed = await frames(stream(["event: sum", "mary\r\ndata: line 1\r\nda", "ta: line 2\r\n\r\ndata: x\n\n"]));

    expect(parsed).toEqual([{ event: "summary", data: "line 1\nline 2" }, { event: "message", data: "x" }]);
  });

  it("decodes a character split between chunks", async () => {
    const bytes = encoder.encode("data: Tổng\n\n");

    expect(await frames(stream([bytes.slice(0, 8), bytes.slice(8)]))).toEqual([{ event: "message", data: "Tổng" }]);
  });
});

function chat(response: () => Response | Promise<Response>) {
  const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
    void init;
    return response();
  });
  return { fetcher, chat: createHttpChat(fetcher) };
}

async function collect(events: AsyncIterable<AskEvent>): Promise<AskEvent[]> {
  const out: AskEvent[] = [];
  for await (const event of events) out.push(event);
  return out;
}

describe("http chat", () => {
  it("posts the question with the time zone and yields the api's events up to done", async () => {
    const { fetcher, chat: http } = chat(() => new Response(stream([frame(STATUS), frame(DONE), frame(STATUS)])));

    const events = await collect(http.ask({ question: "Top products?", conversation_id: "c1", timezone: "Asia/Ho_Chi_Minh" }, new AbortController().signal));

    expect(events).toEqual([STATUS, DONE]);
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("/api/ask");
    expect(JSON.parse(init?.body as string)).toEqual({ question: "Top products?", conversation_id: null, timezone: "Asia/Ho_Chi_Minh" });
  });

  it("continues the api's conversation that a chat's first answer started", async () => {
    const apiId = "6f1c2c3e-8f4b-4c55-9a35-2f0d8a1b7c10";
    const { fetcher, chat: http } = chat(() => new Response(stream([frame(DONE)]), { headers: { "x-conversation-id": apiId } }));
    const signal = new AbortController().signal;

    await collect(http.ask({ question: "Top products?", conversation_id: "c1" }, signal));
    await collect(http.ask({ question: "And last year?", conversation_id: "c1" }, signal));
    await collect(http.ask({ question: "Another chat", conversation_id: "c2" }, signal));

    const sent = fetcher.mock.calls.map(([, init]) => JSON.parse(init?.body as string).conversation_id);
    expect(sent).toEqual([null, apiId, null]);
  });

  it("ends a stopped answer with a stopped notice on the run's trace", async () => {
    const controller = new AbortController();
    const { chat: http } = chat(() => new Response(stream([frame(STATUS)], { signal: controller.signal })));
    const events: AskEvent[] = [];

    for await (const event of http.ask({ question: "q" }, controller.signal)) {
      events.push(event);
      controller.abort();
    }

    expect(events.map((event) => event.event)).toEqual(["status", "error"]);
    expect(events[1]).toMatchObject({ kind: "stopped", trace_id: T.trace_id });
  });

  it("says why the api refused to start an answer", async () => {
    const { chat: http } = chat(() => Response.json({ detail: "too many questions; try again shortly" }, { status: 429 }));

    await expect(collect(http.ask({ question: "q" }, new AbortController().signal))).rejects.toThrow("429: too many questions");
  });

  it("treats a stream that ends before done or error as a lost connection", async () => {
    const { chat: http } = chat(() => new Response(stream([frame(STATUS)])));

    await expect(collect(http.ask({ question: "q" }, new AbortController().signal))).rejects.toThrow("ended before");
  });
});
