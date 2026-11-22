import type { NextConfig } from "next";

import { STATIC_HEADERS } from "./lib/security-headers";

const nextConfig: NextConfig = {
  output: "standalone",
  // No X-Powered-By header naming the framework.
  poweredByHeader: false,
  turbopack: { root: __dirname },
  async headers() {
    return [{ source: "/:path*", headers: STATIC_HEADERS }];
  },
};

export default nextConfig;
