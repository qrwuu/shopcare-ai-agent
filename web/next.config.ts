/// <reference types="node" />
import type { NextConfig } from "next";

const backendUrl = process.env.BACKEND_URL || null;

const nextConfig: NextConfig = {
  devIndicators: false,
  output: "standalone",
  ...(backendUrl && {
    async rewrites() {
      return [
        { source: "/api/:path*", destination: `${backendUrl}/api/:path*` },
        { source: "/uploads/:path*", destination: `${backendUrl}/uploads/:path*` },
      ];
    },
  }),
};

export default nextConfig;
