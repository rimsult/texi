// @vitest-environment node
import { gzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { ContentService } from "../src/services/content";
import { createEmbeddedFetch, gunzipBase64 } from "../src/services/embedded";
import { fixtureManifest, fixturePacks } from "./helpers";

const b64gz = (value: unknown) => gzipSync(Buffer.from(JSON.stringify(value))).toString("base64");

describe("standalone (single-file) content", () => {
  it("decodes gzip+base64 bodies", async () => {
    expect(JSON.parse(await gunzipBase64(b64gz({ ok: "да" })))).toEqual({ ok: "да" });
  });

  it("serves the manifest and packs from embedded data, 404 for anything else", async () => {
    const packs = fixturePacks();
    const embedded: Record<string, string> = { "manifest.json": b64gz(fixtureManifest(packs)) };
    for (const [name, pack] of Object.entries(packs)) embedded[`${name}.json`] = b64gz(pack);
    const fetchImpl = createEmbeddedFetch(embedded);
    const content = new ContentService("packs/", fetchImpl);
    expect((await content.manifest()).decks.map((d) => d.id)).toEqual(["general", "tech"]);
    const tech = await content.ensureLevel("A1", "tech");
    expect(tech.entry("tech:algorithm-n")?.lemma).toBe("algorithm");
    expect((await fetchImpl("packs/nope.json")).status).toBe(404);
    expect((await fetchImpl("packs/toString")).status).toBe(404);
  });
});
