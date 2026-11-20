import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { proxy } from "@/proxy";
import { STATIC_HEADERS, contentSecurityPolicy } from "@/lib/security-headers";

describe("security headers", () => {
  it("allows no inline script without the request's nonce and no framing", () => {
    const policy = contentSecurityPolicy("abc", false);
    const script = policy.split("; ").find((part) => part.startsWith("script-src"));
    expect(script).toBe("script-src 'self' 'nonce-abc' 'strict-dynamic'");
    expect(policy).toContain("frame-ancestors 'none'");
    expect(policy).toContain("object-src 'none'");
  });

  it("gives each page request its own nonce", () => {
    const first = proxy(new NextRequest("http://localhost:3000/")).headers.get("Content-Security-Policy");
    const second = proxy(new NextRequest("http://localhost:3000/")).headers.get("Content-Security-Policy");
    expect(first).toMatch(/'nonce-[A-Za-z0-9+/=]+'/);
    expect(first).not.toBe(second);
  });

  it("sends nosniff, a same-origin referrer, frame denial, no camera, microphone or location and an isolated window", () => {
    expect(Object.fromEntries(STATIC_HEADERS.map(({ key, value }) => [key, value]))).toEqual({
      "X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin", "X-Frame-Options": "DENY",
      "Permissions-Policy": "camera=(), microphone=(), geolocation=()", "Cross-Origin-Opener-Policy": "same-origin",
    });
  });

  it("does not name the framework in X-Powered-By", async () => {
    const { default: config } = await import("@/next.config");
    expect(config.poweredByHeader).toBe(false);
  });
});
