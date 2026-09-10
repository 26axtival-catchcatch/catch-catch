import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = resolve(root, "ppt/presentation-hackathon-10pages.html");
const destination = resolve(root, "frontend/public/presentation");
let html = readFileSync(source, "utf8");

mkdirSync(resolve(destination, "images"), { recursive: true });
for (const [, filename] of html.matchAll(/<img\b[^>]*src="([^"/]+)"/g)) {
  copyFileSync(resolve(root, "ppt", filename), resolve(destination, "images", filename));
  html = html.replaceAll(`src="${filename}"`, `src="/presentation/images/${filename}"`);
}
html = html.replaceAll("../frontend/public/presentation/", "/presentation/");
writeFileSync(resolve(destination, "index.html"), html);
console.log("Synced the presentation HTML and referenced images to frontend/public/presentation.");
