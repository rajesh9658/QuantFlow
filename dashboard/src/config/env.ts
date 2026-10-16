import { z } from "zod";

const EnvSchema = z.object({
  VITE_API_BASE_URL: z.string().url().default("http://localhost:8000"),
  VITE_WS_URL: z.string().url().default("ws://localhost:8000/ws/dashboard"),
  VITE_APP_ENV: z.enum(["development", "staging", "production"]).default("development"),
  VITE_AUTH_MODE: z.enum(["jwt", "dev-bypass"]).default("dev-bypass"),
  VITE_TICKER_THROTTLE_MS: z.coerce.number().int().positive().default(250),
  VITE_RECONNECT_BASE_MS: z.coerce.number().int().positive().default(1000),
  VITE_RECONNECT_MAX_MS: z.coerce.number().int().positive().default(30000),
  VITE_WS_PING_INTERVAL_MS: z.coerce.number().int().positive().default(30000),
  VITE_QUERY_STALE_MS: z.coerce.number().int().positive().default(5000),
});

export const env = EnvSchema.parse(import.meta.env);
