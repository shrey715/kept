import type { NextConfig } from "next";

// The browser talks to /api/*; Next forwards it to the FastAPI service (`kept serve`).
const API = process.env.KEPT_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Dev only: hosts other than localhost that may load the dev server, e.g. this machine's LAN IP
  // so another PC can open it. KEPT_DEV_ORIGINS=10.42.0.1,10.1.37.147
  allowedDevOrigins: (process.env.KEPT_DEV_ORIGINS ?? "").split(",").filter(Boolean),
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/:path*` }];
  },
};

export default nextConfig;
