// @vitest-environment node
import { createRequire } from "node:module";
import { createServer, request as httpRequest, type IncomingMessage } from "node:http";
import type { AddressInfo } from "node:net";

import { afterEach, describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
require("../peer-address.cjs");

let close: (() => void) | null = null;
afterEach(() => close?.());

async function seenBy(headers: Record<string, string>): Promise<{ peer: string | undefined; raw: string[] }> {
  let seen: IncomingMessage | null = null;
  const server = createServer((incoming, response) => {
    seen = incoming;
    response.end();
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  close = () => server.close();
  const { port } = server.address() as AddressInfo;
  await new Promise<void>((resolve, reject) => {
    const outgoing = httpRequest({ host: "127.0.0.1", port, headers }, (response) => { response.resume(); response.on("end", resolve); });
    outgoing.on("error", reject);
    outgoing.end();
  });
  const request = seen as unknown as IncomingMessage;
  const raw = request.rawHeaders.filter((_, index) => index % 2 === 0 && request.rawHeaders[index].toLowerCase() === "x-fitcher-peer")
    .map((_, index) => request.rawHeaders[request.rawHeaders.findIndex((name) => name.toLowerCase() === "x-fitcher-peer") + 1 + index * 2]);
  return { peer: request.headers["x-fitcher-peer"] as string | undefined, raw };
}

describe("the connection address the web server records on each request", () => {
  it("sets the peer header to the connection's own address", async () => {
    expect((await seenBy({})).peer).toBe("127.0.0.1");
  });

  it("replaces a peer header the client sent, in the parsed and the raw headers", async () => {
    const { peer, raw } = await seenBy({ "X-Fitcher-Peer": "203.0.113.9" });

    expect(peer).toBe("127.0.0.1");
    expect(raw).toEqual(["127.0.0.1"]);
  });
});
