import { describe, expect, it } from "vitest";
import { ContentError, ContentService } from "../src/services/content";
import { fixtureManifest, packFetch } from "./helpers";

describe("ContentService", () => {
  it("loads a level together with its ±1 neighbours, once", async () => {
    const { fetch, calls } = packFetch();
    const content = new ContentService("/packs/", fetch);
    await Promise.all([content.ensureLevel("A1"), content.ensureLevel("A1")]);
    expect(calls.filter((c) => c !== "manifest.json").sort()).toEqual(["A1.json", "A2.json"]);
    await content.ensureLevel("B1");
    expect(calls.filter((c) => c !== "manifest.json").sort()).toEqual(["A1.json", "A2.json", "B1.json", "B2.json"]);
    expect(content.lexicon().isReady("B1")).toBe(true);
    expect(content.lexicon().entry("dog-n")?.lemma).toBe("dog");
  });

  it("keeps decks apart: technical packs load into their own lexicon", async () => {
    const { fetch, calls } = packFetch();
    const content = new ContentService("/packs/", fetch);
    const tech = await content.ensureLevel("A1", "tech");
    expect(calls.filter((c) => c !== "manifest.json").sort()).toEqual(["tech-A1.json", "tech-A2.json"]);
    expect(tech.entry("tech:voltage-n")?.domain).toBe("electrical");
    expect(tech.entry("dog-n")).toBeUndefined();
    expect(content.lexicon("general").size).toBe(0);
  });

  it("reports a friendly error offline and retries the manifest later", async () => {
    let up = false;
    const ok = packFetch();
    const fetchImpl = (async (...a: Parameters<typeof fetch>) => {
      if (!up) throw new TypeError("Failed to fetch");
      return ok.fetch(...a);
    }) as typeof fetch;
    const content = new ContentService("/packs/", fetchImpl);
    await expect(content.manifest()).rejects.toBeInstanceOf(ContentError);
    up = true;
    expect((await content.manifest()).version).toBe("test");
  });

  it("rejects an outdated manifest and unexpected packs", async () => {
    const old = (async () => Response.json({ schemaVersion: 1, version: "v1", levels: [] })) as typeof fetch;
    await expect(new ContentService("/packs/", old).manifest()).rejects.toThrow(/перезагрузите/);

    const manifest = fixtureManifest();
    const wrongDeck = (async (input: RequestInfo | URL) =>
      String(input).endsWith("manifest.json")
        ? Response.json(manifest)
        : Response.json({ schemaVersion: 2, deck: "tech", level: "A1", entries: [], questions: [] })) as typeof fetch;
    await expect(new ContentService("/packs/", wrongDeck).ensureLevel("A1")).rejects.toThrow(/Unexpected pack/);

    const notFound = (async (input: RequestInfo | URL) =>
      String(input).endsWith("manifest.json") ? Response.json(manifest) : new Response("", { status: 404 })) as typeof fetch;
    await expect(new ContentService("/packs/", notFound).ensureLevel("C2")).rejects.toThrow(/404/);
  });
});
