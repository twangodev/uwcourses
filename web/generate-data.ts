import { mkdir, writeFile, rm, rename } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import {
  documentEntries,
  buildDocumentAsset,
} from "../src/lib/server/documents/build";
import { sitemapPages, sitemapXml } from "../src/lib/server/sitemap";
import { socialManifest } from "../src/lib/server/social-manifest";
import { status } from "../src/lib/server/data";

const output = resolve(".site/documents");
const staging = output + ".tmp";
await rm(staging, { recursive: true, force: true });
await mkdir(staging, { recursive: true });
async function write(path: string, content: string) {
  const target = resolve(staging, path);
  if (!target.startsWith(staging + "/"))
    throw new Error(`Invalid generated path: ${path}`);
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, content);
}
const entries = await documentEntries();
let next = 0;
await Promise.all(
  Array.from({ length: 4 }, async () => {
    while (next < entries.length) {
      const { path } = entries[next++];
      await write(
        `__documents/${path}`,
        JSON.stringify(await buildDocumentAsset(path)),
      );
      if (next % 2000 === 0)
        console.log(`Documents: ${next}/${entries.length}`);
    }
  }),
);
const pages = await sitemapPages();
const release = await status();
const observed = release.observed_at;
await write(
  "sitemap.xml",
  sitemapXml(
    [...pages.keys()]
      .map((page) => `/sitemaps/${page}`)
      .concat("/blog/sitemap.xml"),
    true,
    observed,
  ),
);
for (const [page, paths] of pages)
  await write(`sitemaps/${page}`, sitemapXml(paths, false, observed));
await write("social/manifest.json", JSON.stringify(await socialManifest()));
await write(
  ".release.json",
  JSON.stringify({
    revision: release.revision,
    projection_id: release.projection_id,
  }),
);
await rm(output, { recursive: true, force: true });
await rename(staging, output);
console.log(`Prepared ${entries.length} serving documents.`);
