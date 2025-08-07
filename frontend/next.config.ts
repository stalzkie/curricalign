/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  async rewrites() {
    return [
      {
        source: "/api/dashboard/:path*",       // Call this in frontend
        destination: "http://127.0.0.1:8000/dashboard/:path*", // Proxies to FastAPI
      },
    ];
  },
};

export default nextConfig;
