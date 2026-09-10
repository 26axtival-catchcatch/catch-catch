import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Keep browser verification separate from the developer's running Next server.
  distDir: process.env.E2E_FRONTEND_PORT ? `.next-e2e-${process.env.E2E_FRONTEND_PORT}` : ".next",
};

export default nextConfig;
