import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // Pin the workspace root to this package — the VPS this was built on has
  // unrelated lockfiles in parent directories that Next.js would otherwise
  // (incorrectly) infer as the monorepo root.
  outputFileTracingRoot: __dirname,
};

export default nextConfig;
