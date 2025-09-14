import type { NextConfig } from 'next';

// Prefer a server-only env for proxies; fallback to public one; finally localhost.
const RAW_API_BASE =
  process.env.API_BASE ?? process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000';

// normalize (no trailing slash)
const API_BASE = RAW_API_BASE.replace(/\/+$/, '');

const nextConfig: NextConfig = {
  reactStrictMode: true,

  async rewrites() {
    // If you don’t want any proxying when API_BASE is empty, you could return [].
    return [
      // Dashboard API
      { source: '/api/dashboard/:path*', destination: `${API_BASE}/api/dashboard/:path*` },
      // Pipeline API
      { source: '/api/pipeline/:path*', destination: `${API_BASE}/api/pipeline/:path*` },
      // Orchestrator API (SSE etc.)
      { source: '/api/orchestrator/:path*', destination: `${API_BASE}/api/orchestrator/:path*` },
      // (Optional) serve backend static files (PDF downloads) through Next
      { source: '/static/:path*', destination: `${API_BASE}/static/:path*` },
    ];
  },
};

console.log('Using API_BASE =', process.env.API_BASE ?? process.env.NEXT_PUBLIC_API_BASE);

export default nextConfig;
