import { buildApp } from "./app";
import { MemoryRepository } from "./memoryRepo";
import { createPool, PgRepository } from "./pgRepo";
import { DEFAULT_OUT, DEFAULT_PACKS, seedIfOutdated } from "./seed";
import { migrate, withStartupLock } from "./migrate";
import { join } from "node:path";

const port = Number(process.env.PORT ?? 8787);
const url = process.env.DATABASE_URL;

let repo;
if (url) {
  const pool = createPool(url);
  await withStartupLock(pool, async () => {
    if (process.env.AUTO_MIGRATE !== "false") await migrate(pool);
    if (process.env.AUTO_SEED !== "false") {
      const seeded = await seedIfOutdated(pool, process.env.PACKS_DIR, process.env.PIPELINE_OUT);
      if (seeded) console.log("Content seeded", seeded);
    }
  });
  repo = new PgRepository(pool);
} else {
  console.warn("DATABASE_URL not set: using in-memory storage (data is lost on restart)");
  repo = new MemoryRepository(process.env.PACKS_DIR ?? DEFAULT_PACKS, join(process.env.PIPELINE_OUT ?? DEFAULT_OUT, "needs_review.json"));
}

const app = await buildApp({ repo, corsOrigin: process.env.CORS_ORIGIN ?? "*", logger: process.env.NODE_ENV !== "test" });
let closing = false;
const shutdown = async () => {
  if (closing) return; // a second signal while draining
  closing = true;
  try {
    await app.close();
    await repo.close();
  } finally {
    process.exit(0);
  }
};
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
await app.listen({ port, host: process.env.HOST ?? "0.0.0.0" });
