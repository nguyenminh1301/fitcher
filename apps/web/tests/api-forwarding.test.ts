// @vitest-environment node
import { describe, expect, it } from "vitest";

import { browserHeaders } from "@/lib/server/api";

describe("headers the web server forwards to the api", () => {
  it("passes the browser's host and origin, so the api checks the address the browser used", () => {
    const forwarded = browserHeaders(new Headers({ host: "localhost:3000", origin: "http://localhost:3000", cookie: "a=b" }));

    expect(Object.fromEntries(forwarded)).toEqual({ "x-forwarded-host": "localhost:3000", origin: "http://localhost:3000" });
  });

  it("sends no origin when the browser sent none", () => {
    expect(Object.fromEntries(browserHeaders(new Headers({ host: "localhost:3000" })))).toEqual({ "x-forwarded-host": "localhost:3000" });
  });

  it("passes the connection address the web server recorded, so the api knows where the browser is", () => {
    const forwarded = browserHeaders(new Headers({ host: "localhost:3000", "x-fitcher-peer": "172.17.0.1" }));

    expect(forwarded.get("x-fitcher-peer")).toBe("172.17.0.1");
  });

  it("ignores a forwarded host sent by the client, which a page could set itself", () => {
    const forwarded = browserHeaders(new Headers({ host: "evil.example:3000", "x-forwarded-host": "localhost:3000" }));

    expect(forwarded.get("x-forwarded-host")).toBe("evil.example:3000");
  });
});
