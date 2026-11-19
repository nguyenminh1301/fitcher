// @vitest-environment node
import { describe, expect, it } from "vitest";

import { BodyTooLarge, forwardBody, readBody, uploadLimit } from "@/lib/server/api";

function chunked(chunks: number, size: number): Request {
  let sent = 0;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (sent++ >= chunks) controller.close();
      else controller.enqueue(new Uint8Array(size));
    },
  });
  return new Request("http://localhost/api/x", { method: "POST", body, duplex: "half" } as RequestInit);
}

describe("request body limits of the web server", () => {
  it("refuses a declared length over the limit before reading the body", async () => {
    const request = new Request("http://localhost/api/x", {
      method: "POST", body: "{}", headers: { "content-length": String(2 * 1024 * 1024) },
    });

    await expect(readBody(request)).rejects.toBeInstanceOf(BodyTooLarge);
    expect(request.bodyUsed).toBe(false);
  });

  it("stops reading a body without a length once it passes the limit", async () => {
    await expect(readBody(chunked(100, 64 * 1024), 256 * 1024)).rejects.toBeInstanceOf(BodyTooLarge);
  });

  it("reads a body under the limit", async () => {
    expect(await readBody(new Request("http://localhost/api/x", { method: "POST", body: '{"a":1}' }))).toBe('{"a":1}');
  });

  it("allows an upload the api's own file limit plus the multipart framing", () => {
    expect(uploadLimit("DOCUMENT_MAX_BYTES", {})).toBe(21 * 1024 * 1024);
    expect(uploadLimit("SOURCE_FILE_MAX_BYTES", { SOURCE_FILE_MAX_BYTES: "1048576" })).toBe(2 * 1024 * 1024);
  });

  it("answers 413 to an upload whose declared length is over the limit without reading or forwarding it", async () => {
    const request = new Request("http://localhost/api/sources/files", {
      method: "POST", body: "x", headers: { "content-length": "1500000000", "content-type": "multipart/form-data; boundary=XX" },
    });

    const response = await forwardBody(request, "/sources/files", uploadLimit("SOURCE_FILE_MAX_BYTES", {}));

    expect(response.status).toBe(413);
    expect(await response.json()).toEqual({ error: "body_too_large" });
    expect(request.bodyUsed).toBe(false);
  });
});
