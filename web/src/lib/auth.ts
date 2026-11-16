import { betterAuth } from "better-auth";
import { nextCookies } from "better-auth/next-js";
import { bearer } from "better-auth/plugins";
import { Pool } from "pg";
import { getAuthDatabaseUrl } from "@/lib/database-url";

const databaseUrl = getAuthDatabaseUrl();

const globalForAuth = globalThis as unknown as {
  authPgPool?: Pool;
};

const pool =
  globalForAuth.authPgPool ??
  new Pool({
    connectionString: databaseUrl || undefined,
    max: Number(process.env.BETTER_AUTH_DB_POOL_SIZE || "10"),
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: Number(
      process.env.BETTER_AUTH_DB_CONNECT_TIMEOUT_MS || "5000",
    ),
  });

if (process.env.NODE_ENV !== "production") {
  globalForAuth.authPgPool = pool;
}

const cookieDomain = process.env.BETTER_AUTH_COOKIE_DOMAIN;

const trustedOrigins = Array.from(
  new Set(
    [
      process.env.BETTER_AUTH_URL || "http://localhost:3000",
      ...(process.env.AUTH_PROXY_ALLOWED_ORIGINS
        ?.split(",")
        .map((origin) => origin.trim().replace(/\/$/, ""))
        .filter(Boolean) || []),
    ].filter(Boolean),
  ),
);

export const auth = betterAuth({
  appName: "CocoCV",
  baseURL: process.env.BETTER_AUTH_URL || "http://localhost:3000",
  secret:
    process.env.BETTER_AUTH_SECRET ||
    "development-only-change-me-before-production-32-chars",
  database: pool,
  trustedOrigins,
  emailAndPassword: {
    enabled: true,
    minPasswordLength: 6,
  },
  // 鉴权层与前端在同一根域的不同子域（如 auth.example.com / example.com）时，
  // 需要把会话 cookie 种到根域，前端才能跨子域读到登录态。
  advanced: cookieDomain
    ? {
        // 跨子域 cookie 走 SameSite=None，必须强制 Secure，否则浏览器拒收
        useSecureCookies: true,
        crossSubDomainCookies: {
          enabled: true,
          domain: cookieDomain,
        },
      }
    : undefined,
  socialProviders: {
    google: {
      clientId: process.env.AUTH_GOOGLE_ID || process.env.GOOGLE_CLIENT_ID || "",
      clientSecret:
        process.env.AUTH_GOOGLE_SECRET || process.env.GOOGLE_CLIENT_SECRET || "",
    },
  },
  plugins: [
    bearer(),
    // Keep this last so server actions and route handlers can forward Set-Cookie.
    nextCookies(),
  ],
});

export type AuthSession = Awaited<ReturnType<typeof auth.api.getSession>>;
