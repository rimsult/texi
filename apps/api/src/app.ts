import cors from "@fastify/cors";
import Fastify, { type FastifyInstance } from "fastify";
import type { Repository, SyncResponse } from "./repo";
import { deckSchema, levelSchema, parseEvents, syncBodySchema } from "./schemas";
import { z } from "zod";

export interface AppOptions {
  repo: Repository;
  corsOrigin?: string;
  logger?: boolean;
}

export async function buildApp({ repo, corsOrigin = "*", logger = false }: AppOptions): Promise<FastifyInstance> {
  const app = Fastify({ logger, bodyLimit: 1024 * 1024 });
  await app.register(cors, {
    origin: corsOrigin === "*" ? true : corsOrigin.split(",").map((s) => s.trim()),
    methods: ["GET", "POST"],
  });

  app.get("/health", async (_req, reply) => {
    try {
      await repo.health();
      return { ok: true };
    } catch {
      return reply.code(503).send({ ok: false });
    }
  });

  app.post("/v1/sync", async (req, reply) => {
    const parsed = syncBodySchema.safeParse(req.body);
    if (!parsed.success) {
      return reply.code(400).send({ error: "invalid_request", issues: parsed.error.issues.slice(0, 20) });
    }
    const { deviceId, events } = parsed.data;
    // Same id twice in one batch counts once (idempotent by event id). Invalid events
    // are rejected individually: they can never become valid, so retrying is pointless.
    const { valid, rejected } = parseEvents(events);
    if (rejected.length) req.log.warn({ deviceId, rejected: rejected.length }, "rejected invalid events");
    const saved = valid.length ? await repo.saveEvents(deviceId, valid) : { accepted: [], duplicates: [] };
    return { ...saved, rejected } satisfies SyncResponse;
  });

  app.get<{ Params: { deviceId: string } }>("/v1/devices/:deviceId/summary", async (req, reply) => {
    if (!z.uuid().safeParse(req.params.deviceId).success) return reply.code(400).send({ error: "invalid_device_id" });
    const summary = await repo.deviceSummary(req.params.deviceId);
    return summary ?? reply.code(404).send({ error: "not_found" });
  });

  app.get("/v1/content/manifest", async (_req, reply) => {
    const manifest = await repo.manifest();
    if (!manifest) return reply.code(404).send({ error: "no_content" });
    return reply.header("cache-control", "public, max-age=300").send(manifest);
  });

  app.get<{ Params: { level: string }; Querystring: { deck?: string } }>("/v1/content/packs/:level", async (req, reply) => {
    const level = levelSchema.safeParse(req.params.level.toUpperCase());
    if (!level.success) return reply.code(404).send({ error: "unknown_level" });
    const deck = deckSchema.safeParse(req.query.deck ?? "general");
    if (!deck.success) return reply.code(404).send({ error: "unknown_deck" });
    const pack = await repo.pack(level.data, deck.data);
    if (!pack) return reply.code(404).send({ error: "no_content" });
    return reply.header("cache-control", "public, max-age=300").send(pack);
  });

  app.get<{ Querystring: { level?: string; limit?: string } }>("/v1/review", async (req, reply) => {
    const level = req.query.level ? levelSchema.safeParse(req.query.level.toUpperCase()) : null;
    if (level && !level.success) return reply.code(400).send({ error: "unknown_level" });
    const limit = Math.min(500, Math.max(1, Number(req.query.limit ?? 100) || 100));
    return { items: await repo.reviewQueue(level?.data, limit) };
  });

  return app;
}
