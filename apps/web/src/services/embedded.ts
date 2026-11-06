/**
 * Standalone build: every content pack is embedded in the page (gzip + base64), and
 * this fetch replacement serves them, so Texi.html works from disk without a server.
 */

function decode(b64: string): Uint8Array<ArrayBuffer> {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export async function gunzipBase64(b64: string): Promise<string> {
  const stream = new Blob([decode(b64)]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Response(stream).text();
}

/** fetch() that answers `…/<file>.json` from embedded packs (file name -> gzip+base64). */
export function createEmbeddedFetch(packs: Record<string, string>): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    const name = String(input instanceof Request ? input.url : input).split("/").pop() ?? "";
    const data = Object.hasOwn(packs, name) ? packs[name] : undefined;
    if (!data) return new Response("not found", { status: 404 });
    return new Response(await gunzipBase64(data), { headers: { "content-type": "application/json" } });
  }) as typeof fetch;
}
