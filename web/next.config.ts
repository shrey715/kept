import type { NextConfig } from "next";

// The browser talks to /api/*; Next forwards it to the FastAPI service (`kept serve`).
const API = process.env.KEPT_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/:path*` }];
  },
};

export default nextConfig;
