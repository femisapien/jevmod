// Copy the shared questions from the Python package into this package, byte for byte.
// The questions must never be rephrased here: every implementation asks Jev the same thing.
import { copyFileSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "..", "..", "..", "jevmod", "categories.json");
const dst = resolve(here, "..", "src", "categories.json");

let before = "";
try {
  before = readFileSync(dst, "utf8");
} catch {
  // first copy
}
copyFileSync(src, dst);
const after = readFileSync(dst, "utf8");
console.log(after === before ? "categories.json already in sync" : `categories.json updated from ${src}`);
