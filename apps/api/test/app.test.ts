import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { buildApp } from "../src/app";
import { MemoryRepository } from "../src/memoryRepo";
import { attemptEventSchema } from "../src/schemas";
import { DEVICE, ev } from "./helpers";

const OTHER = "0b7f5e2a-1c3d-4e5f-8a9b-0c1d2e3f4a5b";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const repo = new MemoryRepository(join(root, "apps/web/public/packs"), join(root, "data-pipeline/out/needs_review.json"));
let app: Awaited<ReturnType<typeof buildApp>>;

beforeAll(async () => {
  app = await buildApp({ repo });
});
afterAll(() => app.close());

const sync = (body: unknown) => app.inject({ method: "POST", url: "/v1/sync", payload: body as object });

describe("API", () => {
  it("reports health", async () => {
    const res = await app.inject("/health");
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ ok: true });
  });

  it("accepts events once and reports duplicates on retry", async () => {
    const events = [ev(), ev({ correct: false, answerId: "cat-n" }), ev({ entryId: "apple-n" })];
    const first = await sync({ deviceId: DEVICE, events });
    expect(first.statusCode).toBe(200);
    expect(first.json()).toEqual({ accepted: events.map((e) => e.id), duplicates: [], rejected: [] });
    const retry = await sync({ deviceId: DEVICE, events });
    expect(retry.json()).toEqual({ accepted: [], duplicates: events.map((e) => e.id), rejected: [] });
  });

  it("accepts events from the tech deck and hard mode (older clients default to general/normal)", async () => {
    const events = [
      ev({ deck: "tech", entryId: "tech:voltage-n", answerId: "tech:current-n", level: "B1", lang: "en", difficulty: "hard" }),
      ev({ difficulty: "hard" }),
    ];
    const res = await sync({ deviceId: OTHER, events });
    expect(res.statusCode).toBe(200);
    expect(res.json().accepted).toHaveLength(2);
    expect((await app.inject(`/v1/devices/${OTHER}/summary`)).json()).toMatchObject({ events: 2, words: 2 });
    expect(attemptEventSchema.parse(ev())).toMatchObject({ deck: "general", difficulty: "normal" });
  });

  it("collapses the same id repeated inside one batch", async () => {
    const e = ev();
    const res = await sync({ deviceId: DEVICE, events: [e, e] });
    expect(res.json()).toEqual({ accepted: [e.id], duplicates: [], rejected: [] });
  });

  it.each([
    ["bad device id", { deviceId: "nope", events: [ev()] }],
    ["empty batch", { deviceId: DEVICE, events: [] }],
    ["too many events", { deviceId: DEVICE, events: Array.from({ length: 501 }, () => ev()) }],
    ["an event without a UUID", { deviceId: DEVICE, events: [ev(), ev({ id: "42" })] }],
    ["events that are not objects", { deviceId: DEVICE, events: ["x"] }],
  ])("rejects a malformed batch: %s", async (_name, body) => {
    const res = await sync(body);
    expect(res.statusCode).toBe(400);
    expect(res.json().error).toBe("invalid_request");
  });

  it.each([
    ["Russian above A2", { deviceId: DEVICE, events: [ev({ level: "B2", lang: "ru" })] }],
    ["future timestamp", { deviceId: DEVICE, events: [ev({ answeredAt: new Date(Date.now() + 3 * 864e5).toISOString() })] }],
    ["bad trainer id", { deviceId: DEVICE, events: [ev({ trainerId: "DROP TABLE" })] }],
    ["negative duration", { deviceId: DEVICE, events: [ev({ durationMs: -1 })] }],
    ["unknown level", { deviceId: DEVICE, events: [ev({ level: "D1" })] }],
    ["unknown deck", { deviceId: DEVICE, events: [ev({ deck: "medical" })] }],
    ["unknown difficulty", { deviceId: DEVICE, events: [ev({ difficulty: "insane" })] }],
    ["tech word in the general deck", { deviceId: DEVICE, events: [ev({ entryId: "tech:voltage-n" })] }],
    ["general word in the tech deck", { deviceId: DEVICE, events: [ev({ deck: "tech" })] }],
  ])("rejects an invalid event on its own: %s", async (_name, body) => {
    const res = await sync(body);
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ accepted: [], duplicates: [], rejected: [body.events[0]!.id] });
  });

  it("stores the valid part of a batch and rejects the rest (a bad event must not block the outbox)", async () => {
    const good = [ev(), ev({ entryId: "tree-n" })];
    const bad = ev({ level: "B2", lang: "ru" });
    const res = await sync({ deviceId: OTHER, events: [good[0], bad, good[1]] });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ accepted: good.map((e) => e.id), duplicates: [], rejected: [bad.id] });
    // A later valid event with the same id wins over the invalid copy.
    const fixed = { ...bad, lang: "en" };
    expect((await sync({ deviceId: OTHER, events: [bad, fixed] })).json()).toEqual({ accepted: [bad.id], duplicates: [], rejected: [] });
  });

  it("summarises a device", async () => {
    const res = await app.inject(`/v1/devices/${DEVICE}/summary`);
    expect(res.statusCode).toBe(200);
    expect(res.json()).toMatchObject({ events: 4, correct: 3, words: 2 });
    expect((await app.inject(`/v1/devices/${"0".repeat(8)}-0000-4000-8000-000000000000/summary`)).statusCode).toBe(404);
    expect((await app.inject("/v1/devices/xyz/summary")).statusCode).toBe(400);
  });

  it("serves content packs with caching headers", async () => {
    const m = await app.inject("/v1/content/manifest");
    expect(m.statusCode).toBe(200);
    expect(m.headers["cache-control"]).toContain("max-age");
    expect(m.json().decks.map((d: { id: string; levels: unknown[] }) => [d.id, d.levels.length])).toEqual([
      ["general", 6],
      ["tech", 6],
    ]);
    const p = await app.inject("/v1/content/packs/a1");
    expect(p.statusCode).toBe(200);
    expect(p.json()).toMatchObject({ schemaVersion: 2, deck: "general", level: "A1" });
    expect((await app.inject("/v1/content/packs/Z9")).statusCode).toBe(404);
  });

  it("serves technical packs with ?deck=tech", async () => {
    const res = await app.inject("/v1/content/packs/B2?deck=tech");
    expect(res.statusCode).toBe(200);
    const pack = res.json();
    expect(pack).toMatchObject({ schemaVersion: 2, deck: "tech", level: "B2" });
    expect(pack.entries.every((e: { id: string; domain?: string }) => e.id.startsWith("tech:") && e.domain)).toBe(true);
    expect(pack.questions.some((q: { hard?: string[] }) => (q.hard?.length ?? 0) >= 2)).toBe(true);
    const bad = await app.inject("/v1/content/packs/B2?deck=medical");
    expect(bad.statusCode).toBe(404);
    expect(bad.json()).toEqual({ error: "unknown_deck" });
  });

  it("exposes the needs_review queue for editors", async () => {
    const res = await app.inject("/v1/review?level=B2&limit=5");
    const { items } = res.json();
    expect(items.length).toBeGreaterThan(0);
    expect(items.length).toBeLessThanOrEqual(5);
    expect(items.every((i: { level: string; reasons: string[] }) => i.level === "B2" && i.reasons.length > 0)).toBe(true);
    expect((await app.inject("/v1/review?level=X")).statusCode).toBe(400);
  });

  it("handles CORS for the configured origin only", async () => {
    const strict = await buildApp({ repo, corsOrigin: "https://lexi.example" });
    const ok = await strict.inject({ method: "OPTIONS", url: "/v1/sync", headers: { origin: "https://lexi.example", "access-control-request-method": "POST" } });
    expect(ok.headers["access-control-allow-origin"]).toBe("https://lexi.example");
    const bad = await strict.inject({ method: "OPTIONS", url: "/v1/sync", headers: { origin: "https://evil.example", "access-control-request-method": "POST" } });
    expect(bad.headers["access-control-allow-origin"]).toBeUndefined();
    await strict.close();
  });

  it("returns 503 when storage is down", async () => {
    const broken = await buildApp({ repo: { ...repo, health: async () => { throw new Error("db down"); } } as never });
    expect((await broken.inject("/health")).statusCode).toBe(503);
    await broken.close();
  });
});
