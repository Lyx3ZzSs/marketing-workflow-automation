import type { NextConfig } from "next";
import { redirectUri } from "./lib/auth-config";

const nextConfig: NextConfig = {
  experimental: { proxyTimeout: 125_000 },
  async redirects() {
    const origin = new URL(redirectUri()).origin;
    if (origin !== "http://127.0.0.1:4186") return [];
    // Normalize the browser origin before Keycloak stores its PKCE callback state.
    return [{
      source: "/:path*",
      has: [{ type: "host", value: "localhost" }],
      destination: `${origin}/:path*`,
      permanent: false,
    }];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.API_BASE_URL ?? "http://127.0.0.1:4187"}/api/:path*`,
      },
    ];
  },
};
export default nextConfig;
