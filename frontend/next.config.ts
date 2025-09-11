/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  async rewrites() {
    const API_BASE =
      process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

    return [
      {
        source: "/api/dashboard/:path*",
        destination: `${API_BASE}/api/dashboard/:path*`,
      },
      {
        source: "/api/pipeline/:path*",
        destination: `${API_BASE}/api/pipeline/:path*`,
      },
      {
        source: "/api/orchestrator/:path*",
        destination: `${API_BASE}/api/orchestrator/:path*`,
      },
    ];
  },
};

export default nextConfig;
