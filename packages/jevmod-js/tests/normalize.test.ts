// Offline: the pre-filter and normalisation must behave like jevmod/judge.py, and the questions must be the
// same file as the Python package's.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  CATEGORIES,
  CATEGORY_NAMES,
  DEFAULT_ACTIONS,
  DEFAULT_THRESHOLDS,
  EXPERIMENTAL,
  Policy,
  cacheKey,
  htmlUnescape,
  isCombining,
  normalize,
  prefilter,
  pyRepr,
} from "../src/index.js";

describe("prefilter", () => {
  it("skips trusted authors, empty and tiny messages, never links", () => {
    expect(prefilter({ id: "a", text: "lol" })).toBe("too short");
    expect(prefilter({ id: "b", text: "buy now http://x.y" })).toBeNull(); // links are never too short
    expect(prefilter({ id: "c", text: "long enough message here", authorTrusted: true })).toBe("trusted author");
    expect(prefilter({ id: "d", text: "   " })).toBe("empty");
  });

  it("counts letters and digits in any script, not words", () => {
    expect(prefilter({ id: "j", text: "こんにちは世界です" })).toBeNull(); // 8 characters, no spaces
    expect(prefilter({ id: "k", text: "こんにちは" })).toBe("too short");
    expect(prefilter({ id: "l", text: "!!! ??? ... ---" })).toBe("too short");
  });

  it("treats bare domains and defanged links as links", () => {
    expect(prefilter({ id: "m", text: "discord.gg/x" })).toBeNull();
    expect(prefilter({ id: "n", text: "go hxxps://bad" })).toBeNull();
    expect(prefilter({ id: "o", text: "x[.]y" })).toBeNull();
  });
});

describe("normalize", () => {
  it("unescapes html, folds fullwidth and ligatures, drops zalgo and zero-width characters", () => {
    // NFKC runs first, so a + U+0301 composes to á and stays (Python does the same); the overlay U+0338 has
    // no composition with z and is dropped, as is the zero-width space.
    expect(normalize("&#39;ＦＲＥＥ&#39; Ｎｉｔｒｏ ﬁ z̸ál​go  &amp; x")).toBe("'FREE' Nitro fi zálgo & x");
    expect(normalize("z̵̶̷a̴l̹g̺o")).toBe("zalgo");
  });

  it("maps the enclosed alphanumeric supplement rows to plain letters", () => {
    expect(normalize("\u{1F130}\u{1F151}\u{1F172}")).toBe("ABC"); // 🄰 🅑 🅲
  });

  it("collapses every kind of whitespace like Python's str.split", () => {
    expect(normalize("a　b\t\nc\x1fd\x85e")).toBe("a b c d e");
    expect(normalize("﻿  spaced   out  ")).toBe("spaced out");
  });

  it("keeps the marks Python keeps (combining class 0) and drops the ones it drops", () => {
    expect(normalize("สวัสดี")).toBe("สวัสดี"); // Thai vowel signs: ccc 0, kept
    expect(normalize("नमस्ते")).toBe("नमसते"); // Devanagari virama U+094D: ccc 9, dropped like Python
    expect(isCombining(0x0e31)).toBe(false); // Thai mai han-akat: Mn but ccc 0, kept by Python
    expect(isCombining(0x094d)).toBe(true); // Devanagari virama: ccc 9, dropped by Python
    expect(isCombining(0x0301)).toBe(true);
  });

  it("handles numeric entities like html.unescape", () => {
    expect(htmlUnescape("&#x27;a&#39;&#150;&#0;")).toBe("'a'–�");
    expect(htmlUnescape("&amp&lt;&unknown;")).toBe("&<&unknown;");
  });
});

describe("cache key and repr match the Python package", () => {
  it("pyRepr quotes like Python's repr()", () => {
    expect(pyRepr("it's fine")).toBe('"it\'s fine"');
    expect(pyRepr('say "hi"')).toBe("'say \"hi\"'");
    expect(pyRepr("both ' and \"\ttab\x01")).toBe("'both \\' and \"\\ttab\\x01'");
  });

  it("cacheKey equals hashlib.sha256(...)[:32] computed in Python", () => {
    const rules = { no_politics: "No political discussion.", b: "it's \"quoted\"\n" };
    expect(cacheKey("Hello World", "gaming", ["spam", "scam"], rules)).toBe("bec74a552cacd69b776ea230431d97bd");
  });
});

describe("categories.json", () => {
  it("is byte-identical to the Python package's file when the monorepo is present", () => {
    const ours = readFileSync(resolve(__dirname, "..", "src", "categories.json"), "utf8");
    let theirs: string | null = null;
    try {
      theirs = readFileSync(resolve(__dirname, "..", "..", "..", "jevmod", "categories.json"), "utf8");
    } catch {
      // published package or a checkout without the Python side: nothing to compare against
    }
    if (theirs !== null) expect(ours).toBe(theirs);
    expect(CATEGORY_NAMES).toEqual([
      "spam",
      "scam",
      "harassment",
      "nsfw",
      "offtopic",
      "selfharm",
      "doxxing",
      "minors",
      "ai_generated",
    ]);
    // Every category needs a threshold and an action, or the npm port silently judges what the Python one does
    // not, or vice versa. This is the check that caught ai_generated missing from both defaults.
    for (const c of CATEGORY_NAMES) {
      expect(DEFAULT_THRESHOLDS[c]).toBeGreaterThan(0);
      expect(DEFAULT_ACTIONS[c]).toBeDefined();
    }
    // Experimental categories ship off, and feedback never moves their threshold.
    for (const c of EXPERIMENTAL) {
      expect(DEFAULT_ACTIONS[c as (typeof CATEGORY_NAMES)[number]]).toBe("off");
      const p = new Policy({});
      expect(p.nudge(c, 0.03)).toBe(DEFAULT_THRESHOLDS[c as (typeof CATEGORY_NAMES)[number]]);
    }
    for (const c of CATEGORY_NAMES) {
      expect(CATEGORIES[c].instructions).toContain("{m}");
      expect(CATEGORIES[c].criteria.true.length).toBeGreaterThan(0);
      expect(CATEGORIES[c].criteria.false.length).toBeGreaterThan(0);
    }
  });
});
