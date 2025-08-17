/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  async rewrites() {
    return [
      // Dashboard API endpoints
      {
        source: "/api/dashboard/:path*",
        destination: "http://127.0.0.1:8000/api/dashboard/:path*",
      },
      // Pipeline API endpoints
      {
        source: "/api/pipeline/:path*",
        destination: "http://127.0.0.1:8000/api/pipeline/:path*",
      },
      // Orchestrator API endpoints
      {
        source: "/api/orchestrator/:path*",
        destination: "http://127.0.0.1:8000/api/orchestrator/:path*",
      },
    ];
  },
};

export default nextConfig;
