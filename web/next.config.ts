import type { NextConfig } from "next";

// The browser talks to /api/*; Next forwards it to the FastAPI service (`kept serve`).
const API = process.env.KEPT_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Dev only: hosts other than localhost that may load the dev server, e.g. this machine's LAN IP
  // so another PC can open it. KEPT_DEV_ORIGINS=10.42.0.1,10.1.37.147
  devIndicators: false,
  allowedDevOrigins: (process.env.KEPT_DEV_ORIGINS ?? "").split(",").filter(Boolean),
  // the Ask can wait on the free LLM tier's rate limit (60 s+ backoffs seen on the bench); Next's default is 30 s
  experimental: { proxyTimeout: 180_000 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/:path*` }];
  },
};

export default nextConfig;
