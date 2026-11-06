import { applyAnswer } from "@lexi/core";
import { describe, expect, it } from "vitest";
import { createMemoryDatabase } from "../src/services/db";
import { DEFAULT_SETTINGS, LocalStore, sanitizeSettings } from "../src/services/store";
import { event, makeStore } from "./helpers";


describe("LocalStore", () => {
  it("keeps a stable anonymous device id", async () => {
    const store = await makeStore();
    const id = await store.deviceId();
    expect(id).toMatch(/^[0-9a-f-]{36}$/);
    expect(await store.deviceId()).toBe(id);
  });

  it("returns default settings and persists changes", async () => {
    const store = await makeStore();
    expect(await store.settings()).toEqual(DEFAULT_SETTINGS);
    await store.saveSettings({ ...DEFAULT_SETTINGS, level: "B2", sessionSize: 20 });
    expect(await store.settings()).toMatchObject({ level: "B2", sessionSize: 20 });
  });

  it("upgrades settings saved by older versions and drops invalid values", async () => {
    expect(DEFAULT_SETTINGS).toMatchObject({ deck: "general", difficulty: "normal" });
    const store = await makeStore();
    await store.setMeta("settings", { trainerId: "word-to-definition", level: "B1", lang: "ru", sessionSize: 10 });
    expect(await store.settings()).toEqual({ ...DEFAULT_SETTINGS, level: "B1" });
    expect(sanitizeSettings({ level: "Z9" as never, deck: "music" as never, difficulty: "insane" as never, sessionSize: 7 })).toEqual(
      DEFAULT_SETTINGS,
    );
    await store.saveSettings({ ...DEFAULT_SETTINGS, deck: "tech", difficulty: "hard" });
    expect(await store.settings()).toMatchObject({ deck: "tech", difficulty: "hard" });
  });

  it.each([
    ["IndexedDB", () => makeStore()],
    ["in-memory fallback", async () => new LocalStore(createMemoryDatabase(), false)],
  ])("records progress and outbox atomically, then acknowledges (%s)", async (_name, make) => {
    const store = await make();
    for (const i of [1, 2, 3]) {
      const e = event(i, i === 3 ? "definition-to-word" : "word-to-definition");
      await store.recordAttempt(e, applyAnswer(undefined, e, e.correct, 0));
    }
    const progress = await store.progressFor("word-to-definition");
    expect([...progress.keys()].sort()).toEqual(["w1-n", "w2-n"]);
    expect(progress.get("w2-n")!.box).toBe(2);
    expect(await store.pendingCount()).toBe(3);
    const pending = await store.pendingEvents(10);
    expect(pending[0]).not.toHaveProperty("queuedAt");
    expect(pending.map((e) => e.id)).toEqual([event(1).id, event(2).id, event(3).id]);
    await store.acknowledge([event(1).id, event(3).id]);
    expect((await store.pendingEvents(10)).map((e) => e.id)).toEqual([event(2).id]);
  });
});
