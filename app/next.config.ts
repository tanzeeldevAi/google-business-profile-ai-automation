import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The Python API runs separately. Proxying through Next means the browser
  // only ever talks to one origin, so there is no CORS dance in development
  // and no mixed-content problem if the UI is ever served over HTTPS.
  async rewrites() {
    const api = process.env.GBP_API_URL || "http://127.0.0.1:8790";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};

export default nextConfig;
