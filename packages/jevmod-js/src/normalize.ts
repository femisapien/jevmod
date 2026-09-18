// Text normalisation and the local pre-filter, ported from jevmod/judge.py. Both run before anything reaches
// Jev and before the cache key is computed, so they must behave like the Python versions.
import { COMBINING_RANGES } from "./combining.js";

export interface Message {
  id: string;
  text: string;
  author?: string;
  channelTopic?: string;
  authorTrusted?: boolean;
}

/** Same pattern as the Python LINK_RE; `\w` is written out because JavaScript's `\w` is ASCII-only. */
export const LINK_RE =
  /(https?:\/\/|hxxps?:\/\/|www\.|\S+\[\.\]\S+|\b[\p{L}\p{N}_-]+\.(?:gg|com|net|org|ru|io|xyz|fr|de|jp|br)\b\/?)/iu;

// Python's html.unescape knows the whole HTML5 entity table. Scraped comments in practice carry the numeric
// forms (&#39;) and a handful of named ones; those are covered here without a runtime dependency.
const NAMED_ENTITIES: Readonly<Record<string, string>> = {
  amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ", copy: "©", reg: "®",
  trade: "™", hellip: "…", mdash: "—", ndash: "–", lsquo: "‘", rsquo: "’",
  ldquo: "“", rdquo: "”", laquo: "«", raquo: "»", bull: "•", middot: "·",
  euro: "€", pound: "£", yen: "¥", cent: "¢", sect: "§", para: "¶",
  deg: "°", plusmn: "±", times: "×", divide: "÷", iexcl: "¡", iquest: "¿",
  frac12: "½", frac14: "¼", frac34: "¾", shy: "­", zwj: "‍", zwnj: "‌",
  ensp: " ", emsp: " ", thinsp: " ", larr: "←", rarr: "→", uarr: "↑",
  darr: "↓", hearts: "♥", diams: "♦", clubs: "♣", spades: "♠", star: "☆",
  agrave: "à", aacute: "á", acirc: "â", atilde: "ã", auml: "ä", aring: "å",
  aelig: "æ", ccedil: "ç", egrave: "è", eacute: "é", ecirc: "ê", euml: "ë",
  igrave: "ì", iacute: "í", icirc: "î", iuml: "ï", ntilde: "ñ", ograve: "ò",
  oacute: "ó", ocirc: "ô", otilde: "õ", ouml: "ö", oslash: "ø", ugrave: "ù",
  uacute: "ú", ucirc: "û", uuml: "ü", yacute: "ý", yuml: "ÿ", szlig: "ß",
  Agrave: "À", Aacute: "Á", Acirc: "Â", Atilde: "Ã", Auml: "Ä", Aring: "Å",
  AElig: "Æ", Ccedil: "Ç", Egrave: "È", Eacute: "É", Ecirc: "Ê", Euml: "Ë",
  Igrave: "Ì", Iacute: "Í", Icirc: "Î", Iuml: "Ï", Ntilde: "Ñ", Ograve: "Ò",
  Oacute: "Ó", Ocirc: "Ô", Otilde: "Õ", Ouml: "Ö", Oslash: "Ø", Ugrave: "Ù",
  Uacute: "Ú", Ucirc: "Û", Uuml: "Ü", Yacute: "Ý",
};
// Legacy names that browsers (and Python) accept without the trailing semicolon.
const LEGACY_NO_SEMICOLON = new Set(["amp", "lt", "gt", "quot", "nbsp", "copy", "reg"]);
// Python maps numeric references in the C1 range to windows-1252, like browsers do.
const CP1252: Readonly<Record<number, number>> = {
  0x80: 0x20ac, 0x82: 0x201a, 0x83: 0x0192, 0x84: 0x201e, 0x85: 0x2026, 0x86: 0x2020, 0x87: 0x2021,
  0x88: 0x02c6, 0x89: 0x2030, 0x8a: 0x0160, 0x8b: 0x2039, 0x8c: 0x0152, 0x8e: 0x017d, 0x91: 0x2018,
  0x92: 0x2019, 0x93: 0x201c, 0x94: 0x201d, 0x95: 0x2022, 0x96: 0x2013, 0x97: 0x2014, 0x98: 0x02dc,
  0x99: 0x2122, 0x9a: 0x0161, 0x9b: 0x203a, 0x9c: 0x0153, 0x9e: 0x017e, 0x9f: 0x0178,
};

/** HTML entities to text, close to Python's `html.unescape` for the entities user content carries. */
export function htmlUnescape(text: string): string {
  if (!text.includes("&")) return text;
  return text.replace(/&(#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*)(;?)/g, (match, body: string, semi: string) => {
    if (body.startsWith("#")) {
      const cp = body[1] === "x" || body[1] === "X" ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10);
      if (cp === 0 || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)) return "�";
      const mapped = CP1252[cp];
      if (mapped !== undefined) return String.fromCodePoint(mapped);
      return String.fromCodePoint(cp);
    }
    const value = NAMED_ENTITIES[body];
    if (value === undefined) return match;
    if (!semi && !LEGACY_NO_SEMICOLON.has(body)) return match;
    return value;
  });
}

// Enclosed Alphanumeric Supplement (🄰 🅐 🅰 …) has no NFKC decomposition; map the three A-Z rows by hand.
const ENCLOSED_BASES = [0x1f130, 0x1f150, 0x1f170] as const;

function mapEnclosed(text: string): string {
  let out = "";
  for (const ch of text) {
    const cp = ch.codePointAt(0) as number;
    let mapped = ch;
    for (const base of ENCLOSED_BASES) {
      if (cp >= base && cp < base + 26) {
        mapped = String.fromCharCode(65 + cp - base);
        break;
      }
    }
    out += mapped;
  }
  return out;
}

/** True when Python's `unicodedata.combining(ch)` is non-zero (canonical combining class != 0). */
export function isCombining(cp: number): boolean {
  let lo = 0;
  let hi = COMBINING_RANGES.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const range = COMBINING_RANGES[mid] as readonly [number, number];
    if (cp < range[0]) hi = mid - 1;
    else if (cp > range[1]) lo = mid + 1;
    else return true;
  }
  return false;
}

const FORMAT_CHAR = /^\p{Cf}$/u;
// Python's str.split() also breaks on \x1c-\x1f and \x85, which JavaScript's \s does not cover.
const WHITESPACE_RUN = /[\s\x1c-\x1f\x85]+/gu;

/**
 * HTML entities to text (scraped comments carry `&#39;`), NFKC (fullwidth, enclosed letters, ligatures to
 * plain), drop combining marks (zalgo) and format characters (zero-width spaces and joiners used to split
 * words, BOM), collapse whitespace.
 */
export function normalize(text: string): string {
  const t = mapEnclosed(htmlUnescape(text)).normalize("NFKC");
  let kept = "";
  for (const ch of t) {
    if (isCombining(ch.codePointAt(0) as number)) continue;
    if (FORMAT_CHAR.test(ch)) continue;
    kept += ch;
  }
  return kept.split(WHITESPACE_RUN).filter((s) => s.length > 0).join(" ");
}

const ALNUM = /^[\p{L}\p{N}]$/u;

/** Letters and digits in any script, counted per code point like Python's `str.isalnum`. */
export function countAlnum(text: string): number {
  let n = 0;
  for (const ch of text) if (ALNUM.test(ch)) n += 1;
  return n;
}

/** Return a reason to skip judging, or null to judge. Counts letters/digits in any script, not words. */
export function prefilter(m: Message, minChars = 8): string | null {
  if (m.authorTrusted) return "trusted author";
  const text = normalize(m.text);
  if (!text) return "empty";
  if (LINK_RE.test(text)) return null; // a link is never too short
  if (countAlnum(text) < minChars) return "too short";
  return null;
}
