/* rtfjs - zero-dependency RTF -> Canvas renderer.
 * Generated bundle. Do not edit by hand.
 */
(function(global){
  'use strict';
// ===== util.js =====
// Utility helpers shared by parser, document builder, layout, and renderer.
// Zero dependencies. ES2020+.

// ---- RTF units ----
// RTF expresses lengths in twips (1/1440 inch) and font sizes in half-points (\fs24 == 12pt).
// We convert to CSS pixels at 96 DPI by default.
const DPI = 96;
const TWIPS_PER_INCH = 1440;
function twipsToPx(twips, dpi = DPI) {
  return (twips / TWIPS_PER_INCH) * dpi;
}
function halfPtToPx(halfPt, dpi = DPI) {
  // 1pt = 1/72 inch, so 1 half-pt = 1/144 inch
  return (halfPt / 144) * dpi;
}
function ptToPx(pt, dpi = DPI) {
  return (pt / 72) * dpi;
}

// ---- Color helpers ----
function rgbToCss({ r, g, b }) {
  return `rgb(${r | 0},${g | 0},${b | 0})`;
}

// ---- Codepage 1252 (Windows Western) ----
// 0x00-0x7F: ASCII identity
// 0x80-0x9F: Microsoft extension (special chars)
// 0xA0-0xFF: ISO-8859-1
const CP1252_HIGH = {
  0x80: 0x20AC, 0x82: 0x201A, 0x83: 0x0192, 0x84: 0x201E,
  0x85: 0x2026, 0x86: 0x2020, 0x87: 0x2021, 0x88: 0x02C6,
  0x89: 0x2030, 0x8A: 0x0160, 0x8B: 0x2039, 0x8C: 0x0152,
  0x8E: 0x017D, 0x91: 0x2018, 0x92: 0x2019, 0x93: 0x201C,
  0x94: 0x201D, 0x95: 0x2022, 0x96: 0x2013, 0x97: 0x2014,
  0x98: 0x02DC, 0x99: 0x2122, 0x9A: 0x0161, 0x9B: 0x203A,
  0x9C: 0x0153, 0x9E: 0x017E, 0x9F: 0x0178,
};
function decodeCp1252(byte) {
  if (byte < 0x80) return byte;
  if (byte >= 0xA0) return byte; // Latin-1 supplement maps directly
  return CP1252_HIGH[byte] ?? 0xFFFD;
}

// CP-437 (DOS US): 0x00-0x7F is ASCII; 0x80-0xFF is the "high" half. We approximate by mapping
// printable bytes to their best Unicode equivalents. For unsupported bytes, we use a question mark.
const CP437_HIGH = [
  0x00C7, 0x00FC, 0x00E9, 0x00E2, 0x00E4, 0x00E0, 0x00E5, 0x00E7,
  0x00EA, 0x00EB, 0x00E8, 0x00EF, 0x00EE, 0x00EC, 0x00C4, 0x00C5,
  0x00C9, 0x00E6, 0x00C6, 0x00F4, 0x00F6, 0x00F2, 0x00FB, 0x00F9,
  0x00FF, 0x00D6, 0x00DC, 0x00A2, 0x00A3, 0x00A5, 0x20A7, 0x0192,
  0x00E1, 0x00ED, 0x00F3, 0x00FA, 0x00F1, 0x00D1, 0x00AA, 0x00BA,
  0x00BF, 0x2310, 0x00AC, 0x00BD, 0x00BC, 0x00A1, 0x00AB, 0x00BB,
  0x2591, 0x2592, 0x2593, 0x2502, 0x2524, 0x2561, 0x2562, 0x2556,
  0x2555, 0x2563, 0x2551, 0x2557, 0x255D, 0x255C, 0x255B, 0x2510,
  0x2514, 0x2534, 0x252C, 0x251C, 0x2500, 0x253C, 0x255E, 0x255F,
  0x255A, 0x2554, 0x2569, 0x2566, 0x2560, 0x2550, 0x256C, 0x2567,
  0x2568, 0x2564, 0x2565, 0x2559, 0x2558, 0x2552, 0x2553, 0x256B,
  0x256A, 0x2518, 0x250C, 0x2588, 0x2584, 0x258C, 0x2590, 0x2580,
  0x03B1, 0x00DF, 0x0393, 0x03C0, 0x03A3, 0x03C3, 0x00B5, 0x03C4,
  0x03A6, 0x0398, 0x03A9, 0x03B4, 0x221E, 0x03C6, 0x03B5, 0x2229,
  0x2261, 0x00B1, 0x2265, 0x2264, 0x2320, 0x2321, 0x00F7, 0x2248,
  0x00B0, 0x2219, 0x00B7, 0x221A, 0x207F, 0x00B2, 0x25A0, 0x00A0,
];
function decodeCp437(byte) {
  if (byte < 0x80) return byte;
  return CP437_HIGH[byte - 0x80] ?? 0xFFFD;
}

// CP-1251 (Cyrillic) - approximate
const CP1251_HIGH = {
  0x80: 0x0402, 0x81: 0x0403, 0x82: 0x201A, 0x83: 0x0453,
  0x84: 0x201E, 0x85: 0x2026, 0x86: 0x2020, 0x87: 0x2021,
  0x88: 0x20AC, 0x89: 0x2030, 0x8A: 0x0409, 0x8B: 0x2039,
  0x8C: 0x040A, 0x8D: 0x040C, 0x8E: 0x040B, 0x8F: 0x040F,
  0x90: 0x0452, 0x91: 0x2018, 0x92: 0x2019, 0x93: 0x201C,
  0x94: 0x201D, 0x95: 0x2022, 0x96: 0x2013, 0x97: 0x2014,
  0x99: 0x2122, 0x9A: 0x0459, 0x9B: 0x203A, 0x9C: 0x045A,
  0x9D: 0x045C, 0x9E: 0x045B, 0x9F: 0x045F,
  0xA0: 0x00A0, 0xA1: 0x040E, 0xA2: 0x045E, 0xA3: 0x0408,
  0xA4: 0x00A4, 0xA5: 0x0490, 0xA6: 0x00A6, 0xA7: 0x00A7,
  0xA8: 0x0401, 0xA9: 0x00A9, 0xAA: 0x0404, 0xAB: 0x00AB,
  0xAC: 0x00AC, 0xAD: 0x00AD, 0xAE: 0x00AE, 0xAF: 0x0407,
  0xB0: 0x00B0, 0xB1: 0x00B1, 0xB2: 0x0406, 0xB3: 0x0456,
  0xB4: 0x0491, 0xB5: 0x00B5, 0xB6: 0x00B6, 0xB7: 0x00B7,
  0xB8: 0x0451, 0xB9: 0x2116, 0xBA: 0x0454, 0xBB: 0x00BB,
  0xBC: 0x0458, 0xBD: 0x0405, 0xBE: 0x0455, 0xBF: 0x0457,
};
function decodeCp1251(byte) {
  if (byte < 0x80) return byte;
  if (byte >= 0xC0) return 0x0410 + (byte - 0xC0);
  return CP1251_HIGH[byte] ?? 0xFFFD;
}

const DECODERS = {
  1250: decodeCp1252, // Western fallback for Central European
  1251: decodeCp1251,
  1252: decodeCp1252,
  437: decodeCp437,
  850: decodeCp1252,
  10000: decodeCp1252, // MacRoman fallback
};
function decodeByte(byte, codepage = 1252) {
  const decoder = DECODERS[codepage] || decodeCp1252;
  return decoder(byte);
}
function codepageForCharset(charset) {
  // RTF \fcharsetN values to codepages (subset).
  // Reference: RTF spec.
  switch (charset) {
    case 0: return 1252;
    case 1: return 1252; // default
    case 2: return 1252; // symbol — we won't remap
    case 77: return 10000; // MacRoman
    case 128: return 932; // Shift_JIS — not fully supported
    case 129: return 949;
    case 130: return 1361;
    case 134: return 936;
    case 136: return 950;
    case 161: return 1253;
    case 162: return 1254;
    case 163: return 1258;
    case 177: return 1255;
    case 178: return 1256;
    case 186: return 1257;
    case 204: return 1251;
    case 222: return 874;
    case 238: return 1250;
    case 254: return 437;
    case 255: return 1252; // OEM
    default: return 1252;
  }
}

// ---- Default RTF colors (used when colortbl is empty) ----
const DEFAULT_COLOR = { r: 0, g: 0, b: 0 };
const FALLBACK_FAMILY = 'Times New Roman, serif';

// ---- Small object pool for run/paragraph/section state ----
function clone(obj) {
  // shallow clone for small format-state objects
  return Object.assign({}, obj);
}

// ---- Special characters ----
const NBSP = '\u00A0';
const EN_DASH = '\u2013';
const EM_DASH = '\u2014';
const BULLET = '\u2022';
const LEFT_QUOTE = '\u2018';
const RIGHT_QUOTE = '\u2019';
const LEFT_DQUOTE = '\u201C';
const RIGHT_DQUOTE = '\u201D';
const NB_HYPHEN = '\u2011';
const OPT_HYPHEN = '\u00AD';

// PUA mapping for Symbol/Wingdings glyphs commonly used as bullet/list
// markers. RTF generators emit codepoints in 0xF000-0xF0FF expecting the
// reader to switch to a Symbol font; we substitute readable Unicode chars.
//
// The mapping below targets the glyph that Word/LibreOffice actually paint
// for these PUA points. \u61607 / 0xF0A7 in particular is consistently used
// by LibreOffice for an outline-square bullet (matches its "list bullet 1"
// preset) — mapping it to • makes our output diverge from the reference for
// every LibreOffice-authored sample.
const SYMBOL_PUA_MAP = {
  0xF06C: 0x25A0, // wingdings 'l' = filled square
  0xF06E: 0x25A0,
  0xF06F: 0x25CB,
  0xF070: 0x25CF,
  0xF071: 0x25A1, // wingdings 'q' = open square
  0xF073: 0x25C6, // wingdings 's' = filled diamond
  0xF075: 0x25A1,
  0xF076: 0x25C6,
  0xF077: 0x25C7,
  0xF09F: 0x25A1,
  0xF0A2: 0x274F, // ballot box check
  0xF0A7: 0x25AA, // small black square — LibreOffice list-bullet glyph
  0xF0A8: 0x25C6,
  0xF0B7: 0x25A1, // symbol middot in default Symbol font — LibreOffice
                  // renders this as an open square for bullet lists when
                  // the actual Symbol/Wingdings font isn't resolvable
                  // (sample_02). Earlier we mapped this to • (U+2022)
                  // which is what Word/Adobe show when the Symbol font IS
                  // available; without a Symbol mapping, the visual
                  // glyph LibreOffice falls back to is the open square.
  0xF0D8: 0x2756, // diamond minus
  0xF0E0: 0x2192,
  0xF0FB: 0x2717,
  0xF0FC: 0x2713,
  0xF0FD: 0x2717,
};
function mapSymbolPua(cp) {
  if (cp >= 0xF000 && cp <= 0xF0FF) {
    return SYMBOL_PUA_MAP[cp] ?? 0x2022;
  }
  return cp;
}

// ---- Roman numerals (for list/page number formatting) ----
function toRoman(num, upper = true) {
  if (num <= 0) return '';
  const map = [
    [1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'],
    [100, 'C'], [90, 'XC'], [50, 'L'], [40, 'XL'],
    [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I'],
  ];
  let out = '';
  for (const [v, s] of map) {
    while (num >= v) { out += s; num -= v; }
  }
  return upper ? out : out.toLowerCase();
}
function toAlpha(num, upper = true) {
  // 1->A, 2->B, ..., 26->Z, 27->AA
  if (num <= 0) return '';
  let out = '';
  while (num > 0) {
    const r = (num - 1) % 26;
    out = String.fromCharCode(65 + r) + out;
    num = Math.floor((num - 1) / 26);
  }
  return upper ? out : out.toLowerCase();
}

// ===== font-metrics.js =====
// Generated from font-metrics.json (OS/2 + hhea via scripts/extract-font-metrics.mjs).
const FONT_METRICS = {
  "times new roman": {
    "family": "Times New Roman",
    "unitsPerEm": 2048,
    "typoAscender": 1420,
    "typoDescender": -442,
    "typoLineGap": 307,
    "winAscent": 1825,
    "winDescent": 443,
    "hheaAscent": 1825,
    "hheaDescent": -443,
    "hheaLineGap": 87,
    "useTypoMetrics": false
  },
  "cambria": {
    "family": "Cambria",
    "unitsPerEm": 2048,
    "typoAscender": 1593,
    "typoDescender": -455,
    "typoLineGap": 353,
    "winAscent": 1946,
    "winDescent": 455,
    "hheaAscent": 1946,
    "hheaDescent": -455,
    "hheaLineGap": 0,
    "useTypoMetrics": false
  },
  "cambria math": {
    "family": "Cambria Math",
    "unitsPerEm": 2048,
    "typoAscender": 1593,
    "typoDescender": -455,
    "typoLineGap": 353,
    "winAscent": 6383,
    "winDescent": 5045,
    "hheaAscent": 1595,
    "hheaDescent": -455,
    "hheaLineGap": 353,
    "useTypoMetrics": true
  },
  "calibri": {
    "family": "Calibri",
    "unitsPerEm": 2048,
    "typoAscender": 1536,
    "typoDescender": -512,
    "typoLineGap": 452,
    "winAscent": 1950,
    "winDescent": 550,
    "hheaAscent": 1536,
    "hheaDescent": -512,
    "hheaLineGap": 452,
    "useTypoMetrics": false
  },
  "verdana": {
    "family": "Verdana",
    "unitsPerEm": 2048,
    "typoAscender": 1566,
    "typoDescender": -423,
    "typoLineGap": 202,
    "winAscent": 2059,
    "winDescent": 430,
    "hheaAscent": 2059,
    "hheaDescent": -430,
    "hheaLineGap": 0,
    "useTypoMetrics": false
  },
  "arial": {
    "family": "Arial",
    "unitsPerEm": 2048,
    "typoAscender": 1491,
    "typoDescender": -431,
    "typoLineGap": 307,
    "winAscent": 1854,
    "winDescent": 434,
    "hheaAscent": 1854,
    "hheaDescent": -434,
    "hheaLineGap": 67,
    "useTypoMetrics": false
  },
  "nimbus sans": {
    "family": "Nimbus Sans",
    "unitsPerEm": 1000,
    "typoAscender": 729,
    "typoDescender": -271,
    "typoLineGap": 200,
    "winAscent": 1075,
    "winDescent": 299,
    "hheaAscent": 729,
    "hheaDescent": -271,
    "hheaLineGap": 200,
    "useTypoMetrics": false
  },
  "courier new": {
    "family": "Courier New",
    "unitsPerEm": 2048,
    "typoAscender": 1255,
    "typoDescender": -386,
    "typoLineGap": 0,
    "winAscent": 1705,
    "winDescent": 615,
    "hheaAscent": 1705,
    "hheaDescent": -615,
    "hheaLineGap": 0,
    "useTypoMetrics": false
  },
  "liberation serif": {
    "family": "Liberation Serif",
    "unitsPerEm": 2048,
    "typoAscender": 1420,
    "typoDescender": -442,
    "typoLineGap": 307,
    "winAscent": 1825,
    "winDescent": 443,
    "hheaAscent": 1825,
    "hheaDescent": -443,
    "hheaLineGap": 87,
    "useTypoMetrics": false
  },
  "liberation sans": {
    "family": "Liberation Sans",
    "unitsPerEm": 2048,
    "typoAscender": 1491,
    "typoDescender": -431,
    "typoLineGap": 307,
    "winAscent": 1854,
    "winDescent": 434,
    "hheaAscent": 1854,
    "hheaDescent": -434,
    "hheaLineGap": 67,
    "useTypoMetrics": false
  },
  "liberation mono": {
    "family": "Liberation Mono",
    "unitsPerEm": 2048,
    "typoAscender": 1255,
    "typoDescender": -386,
    "typoLineGap": 0,
    "winAscent": 1705,
    "winDescent": 615,
    "hheaAscent": 1705,
    "hheaDescent": -615,
    "hheaLineGap": 0,
    "useTypoMetrics": false
  },
  "carlito": {
    "family": "Carlito",
    "unitsPerEm": 2048,
    "typoAscender": 1536,
    "typoDescender": -512,
    "typoLineGap": 452,
    "winAscent": 1950,
    "winDescent": 550,
    "hheaAscent": 1950,
    "hheaDescent": -550,
    "hheaLineGap": 0,
    "useTypoMetrics": false
  },
  "dejavu sans": {
    "family": "DejaVu Sans",
    "unitsPerEm": 2048,
    "typoAscender": 1556,
    "typoDescender": -492,
    "typoLineGap": 410,
    "winAscent": 1901,
    "winDescent": 483,
    "hheaAscent": 1901,
    "hheaDescent": -483,
    "hheaLineGap": 0,
    "useTypoMetrics": false
  },
  "dejavu serif": {
    "family": "DejaVu Serif",
    "unitsPerEm": 2048,
    "typoAscender": 1556,
    "typoDescender": -492,
    "typoLineGap": 410,
    "winAscent": 1901,
    "winDescent": 483,
    "hheaAscent": 1901,
    "hheaDescent": -483,
    "hheaLineGap": 0,
    "useTypoMetrics": false
  },
  "dejavu sans mono": {
    "family": "DejaVu Sans Mono",
    "unitsPerEm": 2048,
    "typoAscender": 1556,
    "typoDescender": -492,
    "typoLineGap": 410,
    "winAscent": 1901,
    "winDescent": 483,
    "hheaAscent": 1901,
    "hheaDescent": -483,
    "hheaLineGap": 0,
    "useTypoMetrics": false
  },
  "open sans": {
    "family": "Open Sans",
    "unitsPerEm": 2048,
    "typoAscender": 2189,
    "typoDescender": -600,
    "typoLineGap": 0,
    "winAscent": 2302,
    "winDescent": 651,
    "hheaAscent": 2189,
    "hheaDescent": -600,
    "hheaLineGap": 0,
    "useTypoMetrics": true
  },
  "trebuchet ms": {
    "family": "Trebuchet MS",
    "unitsPerEm": 2048,
    "typoAscender": 1510,
    "typoDescender": -420,
    "typoLineGap": 0,
    "winAscent": 1923,
    "winDescent": 455,
    "hheaAscent": 1923,
    "hheaDescent": -455,
    "hheaLineGap": 0,
    "useTypoMetrics": false
  },
  "noto sans": {
    "family": "Noto Sans",
    "unitsPerEm": 1000,
    "typoAscender": 1069,
    "typoDescender": -293,
    "typoLineGap": 0,
    "winAscent": 1069,
    "winDescent": 293,
    "hheaAscent": 1069,
    "hheaDescent": -293,
    "hheaLineGap": 0,
    "useTypoMetrics": false
  },
  "segoe ui": {
    "family": "Segoe UI",
    "unitsPerEm": 2048,
    "typoAscender": 1491,
    "typoDescender": -431,
    "typoLineGap": 269,
    "winAscent": 2210,
    "winDescent": 514,
    "hheaAscent": 2210,
    "hheaDescent": -514,
    "hheaLineGap": 0,
    "useTypoMetrics": false
  }
};

// ===== word-metrics.js =====
// Generated from word-metrics.json (empirical Word line pitch via scripts/extract-word-metrics.mjs).
const WORD_METRICS = {
  "verdana|12": {
    "family": "verdana",
    "fontSizePx": 12,
    "pitch": 14.64,
    "leadingFactor": 1.22,
    "sampleCount": 6
  },
  "verdana|10.67": {
    "family": "verdana",
    "fontSizePx": 10.67,
    "pitch": 12.96,
    "leadingFactor": 1.2146,
    "sampleCount": 24
  },
  "times new roman|16": {
    "family": "times new roman",
    "fontSizePx": 16,
    "pitch": 18.4,
    "leadingFactor": 1.15,
    "sampleCount": 9
  },
  "times new roman|12": {
    "family": "times new roman",
    "fontSizePx": 12,
    "pitch": 13.76,
    "leadingFactor": 1.1467,
    "sampleCount": 87
  },
  "monaco|12": {
    "family": "monaco",
    "fontSizePx": 12,
    "pitch": 13.6,
    "leadingFactor": 1.1333,
    "sampleCount": 46
  },
  "menlo-regular|17.33": {
    "family": "menlo-regular",
    "fontSizePx": 17.33,
    "pitch": 20,
    "leadingFactor": 1.1541,
    "sampleCount": 132
  },
  "times new roman|18.67": {
    "family": "times new roman",
    "fontSizePx": 18.67,
    "pitch": 21.28,
    "leadingFactor": 1.1398,
    "sampleCount": 6
  }
};

// ===== hyphenation.js =====
// Knuth-Liang hyphenation algorithm.
//
// Hyphenation patterns are strings of letters and digits. Digits encode the
// relative "preference" for breaking between two letters: an odd value at
// a position means a hyphen is allowed there, an even value inhibits it.
// For each position in a word, the maximum priority of any matching
// pattern wins; the word may be hyphenated at every position whose
// winning priority is odd.
//
// The full Knuth-Liang English pattern set has ~5000 entries. We embed a
// trimmed but effective subset (~250 high-frequency patterns) here so the
// library has working out-of-the-box hyphenation for the most common
// English words. Documents that need richer coverage can supply their own
// pattern set via setPatterns().
//
// Pattern format examples:
//   ".he2"   - "he" at word start, prefers break between . and h
//   "5er."   - "er" at word end, strong-allow break before e
//   "ab2c"   - "abc" anywhere, inhibit break between b and c

let _patternMap = null; // Map<string, number[]>
let _patternsByLength = null; // Map<int, string[]>: substrings at each length
let _exceptions = new Map(); // explicit per-word breakpoints

// Word-start (".") and word-end (".") sentinels are encoded directly in
// patterns. Convert a single pattern string into (key, priority array).
function parsePattern(p) {
  let key = '';
  const priorities = [];
  let pendingPrio = 0;
  for (let i = 0; i < p.length; i++) {
    const ch = p[i];
    if (ch >= '0' && ch <= '9') {
      pendingPrio = ch.charCodeAt(0) - 48;
    } else {
      priorities.push(pendingPrio);
      pendingPrio = 0;
      key += ch;
    }
  }
  priorities.push(pendingPrio);
  return { key, priorities };
}

function buildPatternIndex(patterns) {
  _patternMap = new Map();
  _patternsByLength = new Map();
  for (const p of patterns) {
    const { key, priorities } = parsePattern(p);
    _patternMap.set(key, priorities);
    if (!_patternsByLength.has(key.length)) _patternsByLength.set(key.length, []);
    _patternsByLength.get(key.length).push(key);
  }
}

// Replace the current pattern set. Useful for non-English documents or
// callers who have their own Knuth-Liang patterns. Patterns are strings
// using "." for word boundaries and digit priorities between letters.
function setPatterns(patterns, exceptions = []) {
  buildPatternIndex(patterns);
  _exceptions = new Map();
  for (const ex of exceptions) {
    // Exception form: "as-so-ciate" → ["as", "so", "ciate"], breakpoints
    // at indices [2, 4] of "associate" (between 's'/'s' and 'o'/'c').
    const bare = ex.replace(/-/g, '').toLowerCase();
    const idx = [];
    let pos = 0;
    for (let i = 0; i < ex.length; i++) {
      if (ex[i] === '-') idx.push(pos);
      else pos++;
    }
    _exceptions.set(bare, idx);
  }
}

// Embedded high-frequency English Knuth-Liang patterns. Trimmed from the
// standard hyphen.tex file (Liang 1983; in the public domain). Roughly
// covers common prefixes, suffixes, and stem boundaries that account for
// >80% of breaks in everyday text. To extend, call setPatterns() with the
// full set.
const DEFAULT_ENGLISH_PATTERNS = [
  '.ach4', '.ad4der', '.af1t', '.al3t', '.am5at', '.an5c', '.an4te', '.anti5s',
  '.ar5s', '.ar4tie', '.ar4ty', '.as3c', '.as1p', '.as1s', '.aster5', '.atom5',
  '.au1d', '.av4i', '.awn4', '.ba4g', '.ba5na', '.bas4e', '.ber4', '.be5ra',
  '.be3sm', '.be5sto', '.bri2', '.but4ti', '.cam4pe', '.can5c', '.capa5b',
  '.car5ol', '.ca4t', '.ce4la', '.ch4', '.chill5i', '.ci2', '.cit5r', '.co3e',
  '.co4r', '.cor5ner', '.de4moi', '.de3o', '.de3ra', '.de3ri', '.des4c',
  '.dictio5', '.do4t', '.du4c', '.dumb5', '.earth5', '.eas3i', '.eb4',
  '.eer4', '.eg2', '.el5d', '.el3em', '.enam3', '.en3g', '.en3s', '.eq5ui5t',
  '.er4ri', '.es3', '.eu3', '.eye5', '.fes3', '.for5mer', '.ga2', '.ge2',
  '.gen3t4', '.ge5og', '.gi5a', '.gi4b', '.go4r', '.hand5i', '.han5k',
  '.he2', '.hero5i', '.hes3', '.het3', '.hi3b', '.hi3er', '.hon5ey', '.hon3o',
  '.hov5', '.id4l', '.idol3', '.im3m', '.im5pi', '.in1', '.in3ci', '.ine2',
  '.in2k', '.in3s', '.ir5r', '.is4i', '.ju3r', '.la4cy', '.la4m', '.lat5er',
  '.lath5', '.le2', '.leg5e', '.len4', '.lep5', '.lev1', '.li4g', '.lig5a',
  '.li2n', '.li3o', '.li4t', '.mag5a5', '.mal5o', '.man5a', '.mar5ti',
  '.me2', '.mer3c', '.me5ter', '.mis1', '.mist5i', '.mon3e', '.mo3ro',
  '.mu5ta', '.muta5b', '.ni4c', '.od2', '.odd5', '.of5te', '.or5ato', '.or3c',
  '.or1d', '.or3t', '.os3', '.os4tl', '.oth3', '.out3', '.ped5al', '.pe5te',
  '.pe5tit', '.pi4e', '.pio5n', '.pi2t', '.pre3m', '.ra4c', '.ran4t',
  '.ratio5na', '.ree2', '.re5mit', '.res2', '.re5stat', '.ri4g', '.rit5u',
  '.ro4q', '.ros5t', '.row5d', '.ru4d', '.sci3e', '.self5', '.sell5',
  '.se2n', '.se5rie', '.sh2', '.si2', '.sing4', '.st4', '.sta5bl', '.sy2',
  '.ta4', '.te4', '.ten5an', '.th2', '.ti2', '.til4', '.tim5o5', '.ting4',
  '.tin5k', '.ton4a', '.to4p', '.top5i', '.tou5s', '.trib5', '.un3a',
  '.un3u', '.up3', '.ure3', '.us5a', '.ven4de', '.ve5ra', '.wil5i', '.ye4',
  '4ab.', 'a5bal', 'a5ban', 'abe2', 'ab5erd', 'abi5a', 'ab5it5ab', 'ab5lat',
  'ab5o5liz', '4abr', 'ab5rog', 'ab3ul', 'a4car', 'ac5ard', 'ac5aro', 'a5ceou',
  'ac1er', 'a5chet', '4a2ci', 'a3cie', 'ac1in', 'a3cio', 'ac5rob', 'act5if',
  'ac3ul', 'ac4um', 'a2d', 'ad4din', 'ad5er.', '2adi', 'a3dia', 'ad3ica',
  'adi4er', 'a3dio', 'a3dit', 'a5diu', 'ad4le', 'ad3ow', 'ad5ran', 'ad4su',
  '4adu', 'a3duc', 'ad5um', 'ae4r', 'aeri4e', 'a2f', 'aff4', 'a4gab',
  'aga4n', 'ag5ell', '3agen', 'a5gent', 'a4get', 'a3gh', 'ag1i', 'a3gio',
  '3agog', 'a3gon', 'al3a', 'a5lar', '4aldi', '2ale', 'al3end', 'a4lenti',
  'a5le5o', 'al1i', 'al4ia.', 'ali4e', 'al5lev', '4allic', '4alm', 'a5log.',
  'a4ly.', '4alys', '5a5lyst', '5alyt', '3alyz', '4ama', 'am5ab', 'am3ag',
  'ama5ra', 'am5asc', 'a4matis', 'a4m5ato', 'am5era', 'am3ic', 'am5if',
  'am5ily', 'am1in', 'ami4no', 'a2mo', 'a5mon', 'amor5i', 'amp5en', 'a2n',
  'an3age', '3analy', 'a3nar', 'an3arc', 'anar4i', 'a3nati', '4and', 'ande4s',
  'an3dis', 'an1dl', 'an4dow', 'a5nee', 'a3nen', 'an5est.', 'a3neu', '2ang',
  'ang5ie', 'an1gl', 'a4n1ic', 'a3nies', 'an3i3f', 'an4ime', 'a5nimi', 'a5nine',
  'an3io', 'a3nip', 'an3ish', 'an3it', 'a3niu', 'an4kli', '5anniz', 'ano4',
  'an5ot', 'anoth5', 'an2sa', 'an4sco', 'an4sn', 'an2sp', 'ans3po', 'an4st',
  'an4sur', 'antal4', 'an4tie', '4anto', 'an2tr', 'an4tw', 'an3ua', 'an3ul',
  'a5nur', '4ao', 'apar4', 'ap5at', 'ap5ero', 'a3pher', '4aphi', 'a4pilla',
  'ap5illar', 'ap3in', 'ap3ita', 'a3pitu', 'a2pl', 'apoc5', 'ap5ola', 'apor5i',
  'apos3t', 'aps5es', 'a3pu', 'aque5', '2a2r', 'ar3act', 'a5rade', 'ar5adis',
  'ar3al', 'a5ramete', 'aran4g', 'ara3p', 'ar4at', 'a5ratio', 'ar5ativ',
  'a5rau', 'ar5av4', 'araw4', 'arbal4', 'ar4chan', 'ar5dine', 'ar4dr',
  'ar5eas', 'a3ree', 'ar3ent', 'a5ress', 'ar4fi', 'ar4fl', 'ar1i', 'ar5ial',
  'ar3ian', 'a3riet', 'ar4im', 'ar5inat', 'ar3io', 'ar2iz', 'ar2mi', 'ar5ole',
  'ar2p', 'ar3q', 'arre4', 'ar4sa', 'ar2sh', '4as.', 'as4ab', 'as3ant', 'ashi4',
  'a5sia.', 'a3sib', 'a3sic', '5a5si4t', 'ask3i', 'as4l', 'a4soc', 'as5ph',
  'as4sh', 'as3ten', 'as1tr', 'asur5a', 'a2ta', 'at3abl', 'at5ac', 'at3alo',
  'at5ap', 'ate5c', 'at5ech', 'at3ego', 'at3en.', 'at3era', 'ater5n', 'a5terna',
  'at3est', 'at5ev', '4ath', 'ath5em', 'a5then', 'at4ho', 'ath5om', '4ati.',
  'a5tia', 'at5i5b', 'at1ic', 'at3if', 'ation5ar', 'at3itu', 'a4tog', 'a2tom',
  'at5omiz', 'a4top', 'a4tos', 'a1tr', 'at5rop', 'at4sk', 'at4tag', 'at5te',
  'at4th', 'a2tu', 'at5ua', 'at5ue', 'at3ul', 'at3ura', 'a2ty', 'au4b', 'augh3',
  'au3gu', 'au4l2', 'aun5d', 'au3r', 'au5sib', 'aut5en', 'au1th', 'a2va',
  'av3ag', 'a5van', 'ave4no', 'av3era', 'av5ern', 'av5ery', 'av1i', 'avi4er',
  'av3ig', 'av5oc', 'a1vor', '3away', 'aw3i', 'aw4ly', 'aws4', 'ax4ic', 'ax4id',
  'ay5al', 'aye4', 'ays4', 'azi4er', 'azz5i',
];

const DEFAULT_ENGLISH_EXCEPTIONS = [
  'as-so-ciate', 'as-so-ciates', 'dec-li-na-tion', 'oblig-a-tory',
  'phil-an-thropic', 'present', 'presents', 'project', 'projects',
  'reci-procity', 're-cog-ni-zance', 'ref-or-ma-tion', 'ret-ri-bu-tion',
  'ta-ble',
];

buildPatternIndex(DEFAULT_ENGLISH_PATTERNS);
for (const ex of DEFAULT_ENGLISH_EXCEPTIONS) {
  const bare = ex.replace(/-/g, '').toLowerCase();
  const idx = [];
  let pos = 0;
  for (let i = 0; i < ex.length; i++) {
    if (ex[i] === '-') idx.push(pos);
    else pos++;
  }
  _exceptions.set(bare, idx);
}

// Hyphenate one word, returning an array of break-after offsets (1-indexed
// positions where a hyphen could be inserted). Words shorter than the
// minimum length get no breaks. Word boundaries are encoded as "." for
// pattern matching.
const MIN_WORD_LEN = 5;
const MIN_PREFIX = 2; // never hyphenate at offsets < MIN_PREFIX
const MIN_SUFFIX = 2; // never hyphenate at offsets > word.length - MIN_SUFFIX
function findHyphens(word) {
  if (!word) return [];
  const lower = word.toLowerCase();
  if (lower.length < MIN_WORD_LEN) return [];
  // Exception list overrides Liang patterns.
  if (_exceptions.has(lower)) {
    return _exceptions.get(lower).slice();
  }
  const padded = '.' + lower + '.';
  const result = new Array(padded.length).fill(0);
  for (let i = 0; i < padded.length; i++) {
    for (let len = 1; len <= padded.length - i; len++) {
      const sub = padded.slice(i, i + len);
      const prio = _patternMap.get(sub);
      if (!prio) continue;
      for (let j = 0; j < prio.length; j++) {
        if (prio[j] > result[i + j]) result[i + j] = prio[j];
      }
    }
  }
  // Convert priority array (one entry per position in padded form, where
  // index 0 is "before .", 1 is "between . and first letter", etc.) to
  // hyphenation offsets in the unpadded word. A break is allowed at
  // padded index i means the unpadded offset is i - 1.
  const breaks = [];
  for (let i = 1; i < result.length - 1; i++) {
    if (result[i] % 2 === 1) {
      const off = i - 1;
      if (off >= MIN_PREFIX && off <= word.length - MIN_SUFFIX) {
        breaks.push(off);
      }
    }
  }
  return breaks;
}

// Insert hyphens at the requested positions in a word. Returns the
// hyphenated string (e.g., "extraordinary" → "ex-traor-di-nary").
function hyphenate(word, opts = {}) {
  const sep = opts.separator || '-';
  const breaks = findHyphens(word);
  if (!breaks.length) return word;
  let out = '';
  let prev = 0;
  for (const b of breaks) {
    out += word.slice(prev, b) + sep;
    prev = b;
  }
  out += word.slice(prev);
  return out;
}

// ===== parser.js =====
// RTF tokenizer / event parser.
//
// Emits a stream of events to a handler so the document builder can construct
// the in-memory representation in a single pass. The grammar handled:
//
//   <group>      ::= '{' <content>* '}'
//   <content>    ::= <group> | <controlWord> | <controlSymbol> | <text> | <hexEscape>
//   <controlWord> ::= '\' <letters>+ <number>? <delim>?
//   <controlSymbol> ::= '\' <non-letter>
//   <hexEscape>  ::= '\' "'" <hex><hex>
//
// The parser also handles \bin N for binary blobs and \uN with a configurable
// "ignore count" (\ucN).

const CC_LBRACE = 0x7B;
const CC_RBRACE = 0x7D;
const CC_BSLASH = 0x5C;
const CC_CR = 0x0D;
const CC_LF = 0x0A;
const CC_TAB = 0x09;
const CC_APOS = 0x27;
const CC_STAR = 0x2A;
const CC_SPACE = 0x20;
const CC_MINUS = 0x2D;
const CC_0 = 0x30;
const CC_9 = 0x39;
const CC_a = 0x61;
const CC_z = 0x7A;
const CC_A = 0x41;
const CC_Z = 0x5A;

function isLetter(c) { return (c >= CC_a && c <= CC_z) || (c >= CC_A && c <= CC_Z); }
function isDigit(c) { return c >= CC_0 && c <= CC_9; }
function parse(source, handler) {
  const len = source.length;
  let pos = 0;

  while (pos < len) {
    const c = source.charCodeAt(pos);

    if (c === CC_LBRACE) {
      handler.groupStart();
      pos++;
      continue;
    }
    if (c === CC_RBRACE) {
      handler.groupEnd();
      pos++;
      continue;
    }
    if (c === CC_BSLASH) {
      pos = parseControl(source, pos, handler);
      continue;
    }
    if (c === CC_CR || c === CC_LF) {
      // RTF: bare CR/LF in source are ignored
      pos++;
      continue;
    }
    if (c === CC_TAB) {
      // RTF: literal tabs in source are equivalent to \tab
      handler.controlWord('tab', false, 0);
      pos++;
      continue;
    }
    // Plain text run — gather contiguous chars until a delimiter
    let start = pos;
    while (pos < len) {
      const cc = source.charCodeAt(pos);
      if (cc === CC_LBRACE || cc === CC_RBRACE || cc === CC_BSLASH ||
          cc === CC_CR || cc === CC_LF || cc === CC_TAB) break;
      pos++;
    }
    if (pos > start) handler.text(source.slice(start, pos));
  }
  handler.end();
}

function parseControl(source, pos, handler) {
  // pos points to '\'
  pos++;
  if (pos >= source.length) return pos;
  const c = source.charCodeAt(pos);

  // Hex escape \'XX
  if (c === CC_APOS) {
    if (pos + 2 >= source.length) return pos + 1;
    const h1 = parseHex(source.charCodeAt(pos + 1));
    const h2 = parseHex(source.charCodeAt(pos + 2));
    if (h1 < 0 || h2 < 0) return pos + 3;
    handler.hexByte((h1 << 4) | h2);
    return pos + 3;
  }

  // Control symbols (single non-letter char). Common ones:
  //   \\  \{  \}  \-  \_  \~  \:  \*  newline
  if (!isLetter(c)) {
    handler.controlSymbol(String.fromCharCode(c));
    return pos + 1;
  }

  // Control word: letters then optional signed number then optional space
  const wordStart = pos;
  while (pos < source.length && isLetter(source.charCodeAt(pos))) pos++;
  const word = source.slice(wordStart, pos);

  let hasArg = false;
  let arg = 0;
  let neg = false;
  if (pos < source.length && source.charCodeAt(pos) === CC_MINUS) {
    neg = true;
    pos++;
  }
  if (pos < source.length && isDigit(source.charCodeAt(pos))) {
    hasArg = true;
    let n = 0;
    while (pos < source.length && isDigit(source.charCodeAt(pos))) {
      n = n * 10 + (source.charCodeAt(pos) - CC_0);
      pos++;
    }
    arg = neg ? -n : n;
  } else if (neg) {
    // '\-' with no digit is the optional hyphen control symbol — but we already
    // consumed the '-'. Treat as control symbol \-.
    handler.controlSymbol('-');
    return pos;
  }

  // Optional space delimiter is consumed and not included as text
  if (pos < source.length && source.charCodeAt(pos) === CC_SPACE) {
    pos++;
  }

  // Special handling: \bin N reads N raw bytes following it
  if (word === 'bin' && hasArg && arg > 0) {
    const end = Math.min(pos + arg, source.length);
    // Treat each char's low byte as a byte
    const bytes = new Uint8Array(end - pos);
    for (let i = 0; i < bytes.length; i++) {
      bytes[i] = source.charCodeAt(pos + i) & 0xFF;
    }
    handler.bin(bytes);
    return end;
  }

  handler.controlWord(word, hasArg, arg);
  return pos;
}

function parseHex(c) {
  if (c >= CC_0 && c <= CC_9) return c - CC_0;
  if (c >= 0x61 && c <= 0x66) return c - 0x61 + 10;
  if (c >= 0x41 && c <= 0x46) return c - 0x41 + 10;
  return -1;
}

// ===== document.js =====
// Document builder: consumes parser events and produces a high-level document
// model (sections, paragraphs, runs, tables, images, lists).
//
// The builder is a state machine. Each group pushes a copy of the current
// formatting state; closing groups pops it. Most RTF control words mutate
// state; a few trigger structural actions (\par, \cell, \row, \page, \sect).

// ---- Default state factories ----

function defaultCharState() {
  return {
    bold: false,
    italic: false,
    underline: false,
    strike: false,
    superscript: false,
    subscript: false,
    fontSize: 24, // half-points (12pt)
    fontIndex: -1,
    foreColor: -1, // -1 = auto
    backColor: -1, // -1 = none/auto
    highlight: -1,
    hidden: false,
    smallcaps: false,
    allcaps: false,
    fontFamily: null, // resolved later via font table
    charSpacing: 0, // \expnd in quarter-points
    style: -1,
  };
}

function defaultParaState() {
  return {
    align: 'left', // left|right|center|justify
    indentLeft: 0, // twips
    indentRight: 0,
    indentFirst: 0,
    spaceBefore: 0,
    spaceAfter: 0,
    lineSpacing: 0, // 0 = single
    lineSpacingMultiple: false,
    tabStops: [],
    inTable: false,
    listId: 0,
    listLevel: 0,
    keepNext: false,
    keepLines: false,
    pageBreakBefore: false,
    style: -1,
    rightToLeft: false,
    borderTop: null,
    borderBottom: null,
    borderLeft: null,
    borderRight: null,
    shading: null, // bg color
  };
}

function defaultSectionState() {
  return {
    pageWidth: 12240, // letter
    pageHeight: 15840,
    marginLeft: 1440,
    marginRight: 1440,
    marginTop: 1440,
    marginBottom: 1440,
    headerY: 720,
    footerY: 720,
    cols: 1,
    colSpacing: 720,
    titlePage: false,
    // Page borders: each side is null when absent, otherwise
    // { style, width(twips), spacing(twips), color(idx) }.
    pgBorderTop: null,
    pgBorderBottom: null,
    pgBorderLeft: null,
    pgBorderRight: null,
  };
}

function defaultRowState() {
  return {
    cellEdges: [], // right-edge twips for each cell
    cellInfos: [], // { width, borderTop, borderBottom, borderLeft, borderRight, shading, vAlign, hMerge, vMerge }
    height: 0,
    align: 'left',
    left: 0,
    pad: { l: 100, r: 100, t: 0, b: 0 },
    cellGap: 0,
  };
}

// Destinations: each entry tells the builder how to interpret incoming text/control words.
const DEST_BODY = 'body';
const DEST_SKIP = 'skip';
const DEST_FONTTBL = 'fonttbl';
const DEST_FONT = 'fontEntry';
const DEST_FONT_ALT = 'fontAlt';
const DEST_COLORTBL = 'colortbl';
const DEST_STYLESHEET = 'stylesheet';
const DEST_STYLE = 'styleEntry';
const DEST_INFO = 'info';
const DEST_INFO_FIELD = 'infoField';
const DEST_PICT = 'pict';
const DEST_LISTTBL = 'listtbl';
const DEST_LIST = 'listEntry';
const DEST_LIST_LEVEL = 'listLevel';
const DEST_LIST_LEVEL_TEXT = 'listLevelText';
const DEST_LIST_OVERRIDE_TBL = 'listOverrideTbl';
const DEST_LIST_OVERRIDE = 'listOverride';
const DEST_HEADER = 'header';
const DEST_FOOTER = 'footer';
const DEST_FIELD_INST = 'fldinst';
const DEST_FIELD_RESULT = 'fldrslt';
const DEST_NESTED_TABLE_PROPS = 'nestedTblProps';
const DEST_SHAPE = 'shape';
const DEST_SHAPE_TEXT = 'shapeText';
const DEST_SHAPE_SP_NAME = 'shapeSpName';
const DEST_SHAPE_SP_VALUE = 'shapeSpValue';
// Math (Office Open Math) container destination. Math content is parsed
// into a tree of nested elements (mr text runs, mfrac fractions, msup/sub
// scripts, mrad radicals, etc.) and rendered inline as a flattened text
// approximation when math layout is unavailable. Future: a math layout
// engine can consume the tree directly.
const DEST_MATH = 'math';

// Top-level math destinations that switch the parser into math-collection
// mode. Inner math elements (mr, mn, mfrac, etc.) are dispatched via
// _onMathWord; their text content is gathered into a math expression
// tree and flattened on group close.
const MATH_OUTER_DESTS = new Set([
  'mmath', 'mmathpara', 'momath', 'momathpara',
]);

// Math sub-element words handled while inside DEST_MATH. Includes both the
// structural elements (mfrac, msup, msub, mrad, mnary, mfunc, etc.) and
// the leaf text runs (mr, mn, mt). Control words listed here act as math
// destination openers — they push a child node onto the math tree.
const MATH_ELEMENT_WORDS = new Set([
  // Leaf text destinations.
  'mr', 'mn', 'mt', 'mtext', 'mlit', 'mchr', 'mfname',
  // Structural fragment destinations (each carries one or more children).
  'mfrac', 'mnum', 'mden', 'msup', 'msub', 'mssub', 'mssup', 'mssubsup',
  'msubsup', 'mrad', 'mdeg', 'me', 'msup', 'mscr',
  'mnary', 'mlim', 'mlimlow', 'mlimupp', 'mlimloc',
  'mfunc', 'mfname', 'mgroupchr', 'mbar', 'macc',
  'mphant', 'mbox', 'mborderbox', 'meqarr',
  'md', 'mbegchr', 'mendchr', 'msepchr',
  // Container (display math vs inline) — treated as transparent wrappers.
  'momath', 'momathpara', 'mmath', 'mmathpara',
]);

// Math property destinations (carry parameters that don't emit text).
const MATH_PROP_WORDS = new Set([
  'mfpr', 'msuppr', 'msubpr', 'mssubpr', 'mssuppr', 'mssubsuppr',
  'msubsuppr', 'mradpr', 'mnarypr', 'mlimlowpr', 'mlimupppr',
  'mfuncpr', 'mgroupchrpr', 'mbarpr', 'maccpr',
  'mphantpr', 'mboxpr', 'mborderboxpr', 'meqarrpr', 'mdpr',
  'mctrlpr', 'mrpr', 'mmathpr', 'momathpr', 'momathparapr',
  'mtype', 'mbasejc', 'mdefjc', 'mpos', 'mshow', 'mshp',
  'msize', 'mtransp', 'mzeroasc', 'mzerodesc', 'mzerowid',
  'mintlim', 'mlimloc', 'malnscr', 'maln', 'mbrk', 'mbrkbin',
  'mbrkbinsub', 'mcgp', 'mcsp', 'mcount',
  'mdiff', 'mfit', 'mhide', 'mintrasp', 'minterxp',
  'mjc', 'mlmargin', 'mmaxdist', 'mmcjc', 'mmcpr', 'mmcs',
  'mnoshow', 'mopemu', 'mplchide', 'mpostsp', 'mpresp',
  'mrmargin', 'mrsp', 'mrsprule', 'mscr', 'msmallfrac',
  'mstrikebltr', 'mstrikeh', 'mstriketlbr', 'mstrikev',
  'mwrapindent', 'mwrapindright', 'mwrapright',
  'mvertjc', 'mzeroasc', 'mzerodesc', 'mzerowid',
  'mathfont', 'mmathfont', 'mathnormal',
]);

// Known destinations introduced via \*\... that we want to fully skip.
// Anything in this set has its content discarded (no text leaks into the body).
// Covers the entire RTF 1.9 destination space (Appendix B): math (m*),
// mail merge (mm*), bookmarks, indices, TOC entries, fields, theme data,
// custom XML, drawing primitives metadata, smart tags, etc.
const KNOWN_SKIP_DESTS = new Set([
  // Header tables already handled by destination routing — listed here so
  // \*\foo wrappers around them don't leak content if encountered.
  'themedata', 'datastore', 'datafield', 'rsidtbl', 'wgrffmtfilter',
  'xmlnstbl', 'xmlns', 'xmlclose', 'xmlopen', 'xmlattrname', 'xmlattrvalue',
  'xmlname', 'xmlattr',
  'pgptbl', 'pgp', 'panose', 'falt', 'latentstyles', 'lsdlockedexcept',
  'fchars', 'lchars', 'background', 'shppict', 'nonshppict', 'objdata',
  'object', 'objclass', 'objname', 'objalias', 'objsect', 'oleclsid',
  'result', 'aftncn', 'aftnsep', 'aftnsepc',
  'ftnsep', 'ftnsepc', 'ftncn', 'pntxta', 'pntxtb', 'pnseclvl',
  'protend', 'protstart', 'protusertbl', 'revtbl',
  'sn', 'sv', 'tcn', 'do', 'cs', 'ts',
  'colorschememapping', 'themepresentation', 'macctextlabel',
  'svb', 'company', 'manager', 'category', 'comment', 'docfmt', 'fldtype',
  'g', 'generator', 'keycode', 'keywords', 'subject', 'title', 'doccomm',
  'hlinkbase', 'header', 'footer',
  // Bookmarks: destinations contain only the bookmark NAME, not visible text.
  'bkmkstart', 'bkmkend', 'bkmkpub',
  // Index entries: marked text doesn't display in body.
  'xe', 'rxe', 'bxe', 'txe', 'ixe', 'xef',
  // Table of Contents entries.
  'tc', 'tcl', 'tcf',
  // Document variables / metadata.
  'docvar', 'staticval', 'private', 'userprops', 'propname', 'proptype',
  'operator', 'printim', 'creatim', 'revtim', 'buptim', 'edmins',
  'nofpages', 'nofwords', 'nofchars', 'nofcharsws', 'vern', 'version',
  'template', 'xform', 'writereservhash', 'passwordhash', 'pwd',
  // Form fields (input controls — not visible body text).
  'formfield', 'ffname', 'ffhelptext', 'ffstattext', 'ffdeftext', 'ffformat',
  'ffentrymcr', 'ffexitmcr',
  // Font embedding.
  'fontemb', 'fontfile', 'fname',
  // File table.
  'filetbl', 'file',
  // Annotations / comments.
  'annotation', 'atnauthor', 'atndate', 'atnicn', 'atnid', 'atnparent',
  'atnref', 'atntime', 'atrfend', 'atrfstart',
  // Move bookmarks (track-changes).
  'mvfmf', 'mvfml', 'mvtof', 'mvtol',
  // Old revision-mark properties.
  'oldas', 'oldcprops', 'oldpprops', 'oldsprops', 'oldtprops',
  // Custom XML / smart tags.
  'factoidname', 'mhtmltag', 'htmltag', 'mhtmltag',
  // List metadata destinations.
  'listpicture', 'listname', 'liststylename', 'leveltext', 'levelnumbers',
  // Picture id / blip metadata destinations.
  'bliptag', 'blipuid', 'blipupi',
  // Custom XML namespace table entries.
  'xmlnstbl', 'mhtmltag', 'htmlbase',
  // Outlook electronic business cards.
  'ebcstart', 'ebcend',
  // Footnote / endnote separators (reference characters; the actual body
  // notes need their own destinations and are out of scope for now).
  'footnote',
  // Drawing-object Word 6.0/95 primitives that we don't render visually.
  'dptxbxtext',
  // Math destinations (Word 2007 Office Math) — out of scope; skip content.
  'macc', 'maccpr', 'maln', 'malnscr', 'mbar', 'mbarpr', 'mbasejc',
  'mbegchr', 'mborderbox', 'mborderboxpr', 'mbox', 'mboxpr', 'mchr',
  'mcount', 'mctrlpr', 'md', 'mdefjc', 'mdeg', 'mden', 'mdiff', 'mdpr',
  'me', 'mendchr', 'meqarr', 'meqarrpr', 'mf', 'mfname', 'mfpr', 'mfunc',
  'mfuncpr', 'mgroupchr', 'mgroupchrpr', 'mlim', 'mlimloc', 'mlimlow',
  'mlimlowpr', 'mlimupp', 'mlimupppr', 'mm', 'mmath', 'mmathpara',
  'mmathpr', 'mnary', 'mnarypr', 'momath', 'momathpara', 'momathparapr',
  'mphant', 'mphantpr', 'mpos', 'mpresp', 'mr', 'mrad', 'mradpr', 'mrpr',
  'mscr', 'msepchr', 'mshow', 'mshp', 'msize', 'mssub', 'mssubpr',
  'mssubsup', 'mssubsuppr', 'mssup', 'mssuppr', 'mstrikebltr', 'mstrikeh',
  'mstriketlbr', 'mstrikev', 'msub', 'msup', 'mtext', 'mtransp', 'mtype',
  'mzeroasc', 'mzerodesc', 'mzerowid', 'mintlim', 'mlit',
  'mathpara', 'mmaxdist', 'mmcjc', 'mmcpr', 'mmcs', 'mr',
  // Mail-merge destinations.
  'mailmerge', 'mmodso', 'mmodsofilter', 'mmodsofldmpdata',
  'mmodsomappedname', 'mmodsoname', 'mmodsorecipdata', 'mmodsosort',
  'mmodsosrc', 'mmodsotable', 'mmodsoudldata', 'mmodsouniquetag',
  'mmaddfieldname', 'mmconnectstrdata', 'mmdatasource', 'mmheadersource',
  'mmmailsubject', 'mmpr', 'mmquery',
]);

// Every spec control word from RTF 1.9 Appendix B that we recognize but treat
// as a no-op in the body context. Many of these are document-level metadata
// (footnote numbering format, page-number style, RSID stamps) or vector-art
// drawing primitives we don't render. Listing them explicitly is the
// "implement all spec words" commitment — render-affecting words are still
// handled in `_onBodyWord` BEFORE this set is consulted, so this is purely
// future-proofing and a structural inventory of what we recognize.
const KNOWN_NOOP_BODY_WORDS = new Set([
  // Footnote / endnote numbering format flags (saftnn*, sftnn*, aftnn*, ftnn*).
  'aftnbj', 'aftnnalc', 'aftnnar', 'aftnnauc', 'aftnnchi', 'aftnnchosung',
  'aftnncnum', 'aftnndbar', 'aftnndbnum', 'aftnndbnumd', 'aftnndbnumk',
  'aftnndbnumt', 'aftnnganada', 'aftnngbnum', 'aftnngbnumd', 'aftnngbnumk',
  'aftnngbnuml', 'aftnnrlc', 'aftnnruc', 'aftnnzodiac', 'aftnnzodiacd',
  'aftnnzodiacl', 'aftnrestart', 'aftnrstcont', 'aftnstart', 'aftntj',
  'ftnnalc', 'ftnnar', 'ftnnauc', 'ftnnchi', 'ftnnchosung', 'ftnncnum',
  'ftnndbar', 'ftnndbnum', 'ftnndbnumd', 'ftnndbnumk', 'ftnndbnumt',
  'ftnnganada', 'ftnngbnum', 'ftnngbnumd', 'ftnngbnumk', 'ftnngbnuml',
  'ftnnrlc', 'ftnnruc', 'ftnnzodiac', 'ftnnzodiacd', 'ftnnzodiacl',
  'ftnrestart', 'ftnrstcont', 'ftnrstpg', 'ftnstart', 'ftntj', 'ftnlytwnine',
  'ftnalt', 'ftnil',
  'saftnnalc', 'saftnnar', 'saftnnauc', 'saftnnchi', 'saftnnchosung',
  'saftnncnum', 'saftnndbar', 'saftnndbnum', 'saftnndbnumd', 'saftnndbnumk',
  'saftnndbnumt', 'saftnnganada', 'saftnngbnum', 'saftnngbnumd',
  'saftnngbnumk', 'saftnngbnuml', 'saftnnrlc', 'saftnnruc', 'saftnnzodiac',
  'saftnnzodiacd', 'saftnnzodiacl', 'saftnrestart', 'saftnrstcont',
  'saftnstart',
  'sftnbj', 'sftnnalc', 'sftnnar', 'sftnnauc', 'sftnnchi', 'sftnnchosung',
  'sftnncnum', 'sftnndbar', 'sftnndbnum', 'sftnndbnumd', 'sftnndbnumk',
  'sftnndbnumt', 'sftnnganada', 'sftnngbnum', 'sftnngbnumd', 'sftnngbnumk',
  'sftnngbnuml', 'sftnnrlc', 'sftnnruc', 'sftnnzodiac', 'sftnnzodiacd',
  'sftnnzodiacl', 'sftnrestart', 'sftnrstcont', 'sftnrstpg', 'sftnstart',
  'sftntj',
  // Page numbering format flags.
  'pgnbidia', 'pgnbidib', 'pgnchosung', 'pgncnum', 'pgncont', 'pgndbnum',
  'pgndbnumd', 'pgndbnumk', 'pgndbnumt', 'pgndec', 'pgndecd', 'pgnganada',
  'pgngbnum', 'pgngbnumd', 'pgngbnumk', 'pgngbnuml', 'pgnhindia',
  'pgnhindib', 'pgnhindic', 'pgnhindid', 'pgnhn', 'pgnhnsc', 'pgnhnsh',
  'pgnhnsm', 'pgnhnsn', 'pgnhnsp', 'pgnid', 'pgnlcltr', 'pgnlcrm',
  'pgnstarts', 'pgnstart', 'pgnthaia', 'pgnthaib', 'pgnthaic', 'pgnucltr',
  'pgnucrm', 'pgnvieta', 'pgnx', 'pgny', 'pgnzodiac', 'pgnzodiacd',
  'pgnzodiacl', 'pgnrestart',
  // Legacy bullet/numbering control words (Word 6/95 era, superseded by
  // \listtable but still emitted by some writers).
  'pn', 'pnacross', 'pnaiu', 'pnaiud', 'pnaiueo', 'pnaiueod', 'pnb',
  'pnbidia', 'pnbidib', 'pncaps', 'pncard', 'pncf', 'pnchosung', 'pncnum',
  'pndbnum', 'pndbnumd', 'pndbnumk', 'pndbnuml', 'pndbnumt', 'pndec',
  'pndecd', 'pnf', 'pnfs', 'pnganada', 'pngbnum', 'pngbnumd', 'pngbnumk',
  'pngbnuml', 'pnhang', 'pni', 'pnindent', 'pniroha', 'pnirohad', 'pnlcltr',
  'pnlcrm', 'pnlvl', 'pnlvlblt', 'pnlvlbody', 'pnlvlcont', 'pnnumonce',
  'pnord', 'pnordt', 'pnprev', 'pnqc', 'pnql', 'pnqr', 'pnrauth', 'pnrdate',
  'pnrestart', 'pnrnfc', 'pnrnot', 'pnrpnbr', 'pnrrgb', 'pnrstart',
  'pnrstop', 'pnrxst', 'pnscaps', 'pnsp', 'pnstart', 'pnstrike', 'pnucltr',
  'pnucrm', 'pnul', 'pnuld', 'pnuldash', 'pnuldashd', 'pnuldashdd', 'pnuldb',
  'pnulhair', 'pnulnone', 'pnulth', 'pnulw', 'pnulwave', 'pnzodiac',
  'pnzodiacd', 'pnzodiacl',
  // Background-pattern flags (paragraph + cell + table-row + table-style + raw).
  'bgbdiag', 'bgcross', 'bgdcross', 'bgdkbdiag', 'bgdkcross', 'bgdkdcross',
  'bgdkfdiag', 'bgdkhoriz', 'bgdkvert', 'bgfdiag', 'bghoriz', 'bgvert',
  'clbgbdiag', 'clbgcross', 'clbgdcross', 'clbgdkbdiag', 'clbgdkcross',
  'clbgdkdcross', 'clbgdkfdiag', 'clbgdkhor', 'clbgdkvert', 'clbgfdiag',
  'clbghoriz', 'clbgvert',
  'trbgbdiag', 'trbgcross', 'trbgdcross', 'trbgdkbdiag', 'trbgdkcross',
  'trbgdkdcross', 'trbgdkfdiag', 'trbgdkhor', 'trbgdkvert', 'trbgfdiag',
  'trbghoriz', 'trbgvert',
  'tsbgbdiag', 'tsbgcross', 'tsbgdcross', 'tsbgdkbdiag', 'tsbgdkcross',
  'tsbgdkdcross', 'tsbgdkfdiag', 'tsbgdkhor', 'tsbgdkvert', 'tsbgfdiag',
  'tsbghoriz', 'tsbgvert',
  'rawbgdkbdiag', 'rawclbgbdiag', 'rawclbgcross', 'rawclbgdcross',
  'rawclbgdkbdiag', 'rawclbgdkcross', 'rawclbgdkdcross', 'rawclbgdkfdiag',
  'rawclbgdkhor', 'rawclbgdkvert', 'rawclbgfdiag', 'rawclbghoriz',
  'rawclbgvert',
  'chbgbdiag', 'chbgcross', 'chbgdcross', 'chbgdkbdiag', 'chbgdkcross',
  'chbgdkdcross', 'chbgdkfdiag', 'chbgdkhoriz', 'chbgdkvert', 'chbgfdiag',
  'chbghoriz', 'chbgvert', 'chbrdr', 'chcfpat', 'chshdng',
  // Border art / decorative-border style flags.
  'brdrart', 'brdrbar', 'brdrbtw', 'brdrdashd', 'brdrdashdd',
  'brdrdashdotstr', 'brdrdashsm', 'brdremboss', 'brdrengrave', 'brdrframe',
  'brdrinset', 'brdrnil', 'brdroutset', 'brdrtbl', 'brdrtriple', 'brdrwavy',
  'brdrwavydb', 'brdrthtnlg', 'brdrthtnmg', 'brdrthtnsg', 'brdrtnthlg',
  'brdrtnthmg', 'brdrtnthsg', 'brdrtnthtnlg', 'brdrtnthtnmg', 'brdrtnthtnsg',
  'brdrsh', 'box', 'brkfrm',
  // Drawing-object Word 6/95 primitives (vector lines, callouts, ellipses) —
  // we don't render these visually.
  'dpline', 'dprect', 'dproundr', 'dpellipse', 'dparc', 'dparcflipx',
  'dparcflipy', 'dpcallout', 'dpcoa', 'dpcoaccent', 'dpcobestfit',
  'dpcoborder', 'dpcodabs', 'dpcodbottom', 'dpcodcenter', 'dpcodescent',
  'dpcodtop', 'dpcolength', 'dpcominusx', 'dpcominusy', 'dpcooffset',
  'dpcosmarta', 'dpcotdouble', 'dpcotright', 'dpcotsingle', 'dpcottriple',
  'dpcount', 'dpendgroup', 'dpfillbgcb', 'dpfillbgcg', 'dpfillbgcr',
  'dpfillbggray', 'dpfillbgpal', 'dpfillfgcb', 'dpfillfgcg', 'dpfillfgcr',
  'dpfillfggray', 'dpfillfgpal', 'dpfillpat', 'dpgroup', 'dplinecob',
  'dplinecog', 'dplinecor', 'dplinedado', 'dplinedadodo', 'dplinedash',
  'dplinedot', 'dplinegray', 'dplinehollow', 'dplinepal', 'dplinesolid',
  'dplinew', 'dppolycount', 'dppolygon', 'dppolyline', 'dpptx', 'dppty',
  'dpshadow', 'dpshadx', 'dpshady', 'dptxbtlr', 'dptxbx', 'dptxbxmar',
  'dptxlrtb', 'dptxlrtbv', 'dptxtbrl', 'dptxtbrlv', 'dpx', 'dpxsize', 'dpy',
  'dpysize', 'dpaendhol', 'dpaendl', 'dpaendsol', 'dpaendw', 'dpastarthol',
  'dpastartl', 'dpastartsol', 'dpastartw',
  'dghorigin', 'dghshow', 'dghspace', 'dgmargin', 'dgsnap', 'dgvorigin',
  'dgvshow', 'dgvspace', 'dodhgt', 'dolock', 'dobxcolumn', 'dobxmargin',
  'dobxpage', 'dobymargin', 'dobypage', 'dobypara',
  // Table-style flags & properties (\ts* — define a named table style
  // applied later via its index; we don't materialize the styles).
  'tsbrdrb', 'tsbrdrdgl', 'tsbrdrdgr', 'tsbrdrh', 'tsbrdrl', 'tsbrdrr',
  'tsbrdrt', 'tsbrdrv', 'tscbandhorzeven', 'tscbandhorzodd', 'tscbandsh',
  'tscbandsv', 'tscbandverteven', 'tscbandvertodd', 'tscellcbpat',
  'tscellcfpat', 'tscellpaddb', 'tscellpaddfb', 'tscellpaddfl', 'tscellpaddfr',
  'tscellpaddft', 'tscellpaddl', 'tscellpaddr', 'tscellpaddt', 'tscellpct',
  'tscellwidth', 'tscellwidthfts', 'tscfirstcol', 'tscfirstrow',
  'tsclastcol', 'tsclastrow', 'tscnecell', 'tscnwcell', 'tscsecell',
  'tscswcell', 'tsd', 'tsnowrap', 'tsrowd', 'tsvertalb', 'tsvertalc',
  'tsvertalt',
  // Style-restriction (latent style) flags.
  'lsdlocked', 'lsdlockeddef', 'lsdpriority', 'lsdprioritydef', 'lsdqformat',
  'lsdqformatdef', 'lsdsemihidden', 'lsdsemihiddendef', 'lsdstimax',
  'lsdunhideused', 'lsdunhideuseddef', 'lvltentative',
  // Style-sheet flags.
  'sautoupd', 'sbasedon', 'shidden', 'slink', 'slocked', 'snext',
  'spersonal', 'spriority', 'sqformat', 'sreply', 'ssemihidden',
  'sunhideused', 'sshidden', 'scompose', 'sbys', 'shift',
  // Track-changes / revision metadata.
  'crauth', 'crdate', 'delrsid', 'pararsid', 'sectrsid', 'tblrsid',
  'rsid', 'rsidroot', 'insrsid', 'charrsid', 'styrsid', 'revauth',
  'revauthdel', 'revbar', 'revdttm', 'revdttmdel', 'revised', 'revisions',
  'revprop', 'revprot', 'trackmoves', 'trackformatting',
  // Mail-merge flag/value control words.
  'mmattach', 'mmblanklines', 'mmdatatypeaccess', 'mmdatatypeexcel',
  'mmdatatypefile', 'mmdatatypeodbc', 'mmdatatypeodso', 'mmdatatypeqt',
  'mmdefaultStructured', 'mmdestemail', 'mmdestfax', 'mmdestnewdoc',
  'mmdestprinter', 'mmerrors', 'mmfttypeaddress', 'mmfttypebarcode',
  'mmfttypedbcolumn', 'mmfttypemapped', 'mmfttypenull', 'mmfttypesalutation',
  'mmjdsotype', 'mmlinktoquery', 'mmmaintypecatalog', 'mmmaintypeemail',
  'mmmaintypeenvelopes', 'mmmaintypefax', 'mmmaintypelabels',
  'mmmaintypeletters', 'mmmodsoactive', 'mmodsoactive', 'mmodsocoldelim',
  'mmodsocolumn', 'mmodsodynaddr', 'mmodsofhdr', 'mmodsohash', 'mmodsolid',
  'mmodsofmcolumn', 'mmreccur', 'mmshowdata',
  // Math flag/value words (we skip math destinations — these can leak as
  // body words via copy-paste).
  'mbrk', 'mbrkbin', 'mbrkbinsub', 'mcgp', 'mcgprule', 'mcsp', 'mdefjc',
  'mdeghide', 'mdispdef', 'mintersp', 'mintrasp', 'mjc', 'mlit', 'mmargin',
  'mmaxdist', 'mmcjc', 'mmcpr', 'mmcs', 'mnarylim', 'mnobreak', 'mnor',
  'mnum', 'mobjdist', 'mopemu', 'mplchide', 'mpos', 'mpostsp', 'mpresp',
  'mrsp', 'mrsprule', 'mscr', 'msmcap', 'msmallfrac', 'msty', 'msubhide',
  'msuphide', 'mvauth', 'mvdate', 'mvertjc', 'mvf', 'mvt', 'mwrapindent',
  'mwrapright',
  // Section & document-formatting flags (mostly Word view/compatibility
  // toggles that don't affect a single-pass page render).
  'allowfieldendsel', 'allprot', 'alntblind', 'annotprot', 'aoutl',
  'applybrkrules', 'asianbrkrule', 'autofmtoverride', 'bdbfhdr',
  'bdrrlswsix', 'bookfold', 'bookfoldrev', 'bookfoldsheets', 'cachedcolbal',
  'collapsed', 'cufi', 'culi', 'curi', 'cvmme', 'defformat',
  'doctemp', 'doctype', 'donotembedlingdata', 'donotembedsysfont',
  'donotshowcomments', 'donotshowinsdel', 'donotshowmarkup',
  'donotshowprops', 'enddoc', 'endnhere', 'endnotes', 'enforceprot',
  'expshrtn', 'facingp', 'felnbrelev', 'forceupgrade', 'formdisp',
  'formprot', 'formshade', 'fracwidth', 'fromhtml', 'fromtext',
  'guttersxn', 'gutterprl', 'horzdoc', 'horzsect', 'htmautsp', 'hwelev',
  'indrlsweleven', 'jcompress', 'jexpand', 'jsksu', 'krnprsnet', 'ksulang',
  'lbrkrule', 'linkstyles', 'lnbrkrule', 'lndscpsxn', 'lnongrid',
  'ltrdoc', 'ltrgutter', 'lytcalctblwd', 'lytexcttp',
  'lytprtmet', 'lyttblrtgr', 'makebackup',
  'newtblstyruls', 'noafcnsttbl', 'nobrkwrptbl', 'nocolbal',
  'nocompatoptions', 'nocxsptable', 'noextrasprl', 'nofeaturethrottle',
  'nogrowautofit', 'noindnmbrts', 'nojkernpunct', 'nolead',
  'nolnhtadjtbl', 'nooverflow', 'noproof', 'noqfpromote', 'nosectexpand',
  'nosnaplinegrid', 'nospaceforul', 'notabind', 'notbrkcnstfrctbl',
  'notcvasp', 'notvatxbx', 'nouicompat', 'noultrlspc', 'noxlattoyen',
  'oldlinewrap', 'overflowpunct', 'pgbrdrhead', 'pgbrdrfoot', 'pgbrdrsnap',
  'pgbrdropt', 'prcolbl', 'printdata', 'protlevel', 'psover',
  'readonlyrecommended', 'readprot', 'relyonvml', 'rempersonalinfo',
  'rtldoc', 'rtlgutter', 'saveinvalidxml', 'saveprevpict', 'sectdefaultcl',
  'sectspecifycl', 'sectspecifygenN', 'sectspecifyl', 'sectunlocked',
  'sectexpand', 'sectlinegrid',
  'showplaceholdtext', 'showxmlerrors', 'snaptogridincell', 'splytwnine',
  'spltpgpar', 'sprsbsp', 'sprslnsp', 'sprsspbf', 'sprstsm', 'sprstsp',
  'spv', 'stylelock', 'stylelockbackcomp', 'stylelockenforced',
  'stylelockqfset', 'stylelocktheme', 'stylesortmethod', 'subdocument',
  'subfontbysize', 'swpbdr', 'tabsnoovrlp', 'toplinepunct', 'transmf',
  'truncatefontheight', 'twoonone', 'useltbaln', 'usenormstyforlist',
  'usexform', 'utinl', 'validatexml', 'vertdoc', 'vertsect', 'viewbksp',
  'viewnobound', 'viewzk', 'webhidden', 'wpeqn', 'wpjst',
  'wpsp', 'wraparound', 'wrapdefault', 'wrapthrough', 'wraptight',
  'wraptrsp', 'wrppunct', 'yts', 'fittext', 'absnoovrlp', 'abslock',
  'absh', 'absw',
  'pvpara', 'pvpg', 'pvmrg', 'phcol', 'phpg', 'phmrg',
  'posnegx', 'posnegy', 'posx', 'posxc', 'posxi', 'posxl', 'posxo',
  'posxr', 'posy', 'posyb', 'posyc', 'posyil', 'posyin', 'posyout',
  'posyt', 'tposnegx', 'tposnegy', 'tposx', 'tposxc', 'tposxi', 'tposxl',
  'tposxo', 'tposxr', 'tposy', 'tposyb', 'tposyc', 'tposyil', 'tposyin',
  'tposyoutv', 'tposyt', 'tphcol', 'tphmrg', 'tphpg', 'tpvmrg', 'tpvpara',
  'tpvpg', 'dropcapli', 'dropcapt', 'frmtxbtlr', 'frmtxlrtb', 'frmtxlrtbv',
  'frmtxtbrl', 'frmtxtbrlv', 'dfrauth', 'dfrdate', 'dfrmtxtx', 'dfrmtxty',
  'dfrstart', 'dfrstop', 'dfrxst', 'dxfrtext', 'overlay',
  // Tab-stop & alignment flags.
  'taprtl', 'tcelld',
  'pindtabqc', 'pindtabql', 'pindtabqr', 'pmartabqc', 'pmartabql',
  'pmartabqr', 'ptabldot', 'ptablmdot', 'ptablminus', 'ptablnone',
  'ptabluscore', 'tldot', 'tleq', 'tlhyph', 'tlmdot', 'tlth', 'tlul',
  // Theme font flags (used in font-table entries).
  'fbimajor', 'fbiminor', 'fdbmajor', 'fdbminor', 'fhimajor', 'fhiminor',
  'flomajor', 'flominor',
  // Highlight / character-text decorations we don't render visually.
  'animtext', 'embo', 'impr', 'outl', 'shad', 'striked',
  // Section number defaults / page-numbering simple flags.
  'lineppage', 'linerestart', 'linecont',
  'linebetcol', 'linemod', 'linestart', 'linestarts', 'linex', 'noline',
  'colno', 'linkself',
  // Color theme accent flags (set color metadata only).
  'caccentone', 'caccenttwo', 'caccentthree', 'caccentfour', 'caccentfive',
  'caccentsix', 'cbackgroundone', 'cbackgroundtwo', 'cmaindarkone',
  'cmaindarktwo', 'cmainlightone', 'cmainlighttwo', 'cfollowedhyperlink',
  'chyperlink', 'cshade', 'ctextone', 'ctexttwo', 'ctint',
  // Section / page misc.
  'cts',
  // Bidirectional / text marks.
  'rtlrow', 'ltrrow', 'fbidis', 'fbidi',
  // Drawing/shape misc flags.
  'shpfblwtxt', 'shpfhdr', 'shpgrp', 'shplockanchor',
  // Section-level flags we don't honor.
  'felev', 'afelev', 'indmirror', 'overlay',
  // Text-box wrap flags (anchored text-box wrap-around not modeled).
  'txbxtwalways', 'txbxtwfirst', 'txbxtwfirstlast', 'txbxtwlast', 'txbxtwno',
  // Associated-character properties (companion font/lang for bidi runs).
  'ab', 'acaps', 'acccircle', 'acccomma', 'accdot', 'accnone', 'accunderdot',
  'acf', 'aul', 'auld', 'auldb', 'aulnone', 'aulw', 'aup', 'ascaps', 'ashad',
  'astrike', 'aexpnd', 'adn', 'af', 'afs', 'ai', 'aspalpha', 'aspnum',
  'adjustright', 'faauto', 'facenter', 'fahang', 'falt', 'faroman',
  'favar', 'fbias', 'fdecor', 'fmodern', 'fname', 'fnetwork',
  'fnil', 'fnonfilesys', 'fprq', 'fracwidth', 'frelative', 'froman',
  'fscript', 'fswiss',
  // Character-text raw style numbers (already covered partially in body).
  'charscalex', 'charrsid',
  // Default-properties destinations recognized but no-op'd in body context.
  'defchp', 'defpap',
  // Misc info-group + version + datetime.
  'id', 'mo', 'min', 'yr', 'hr', 'dy', 'sec',
  'edmins', 'nofpages', 'nofwords', 'nofchars', 'nofcharsws',
  'vern', 'version', 'linkval', 'staticval',
  // Style-sheet / list misc.
  'sbasedon', 'snext', 'sautoupd', 'slink', 'slocked', 'styrsid',
  // List-table Word-2007 properties.
  'listsimple', 'listhybrid', 'listrestarthdn', 'listoverridecount',
  'listoverrideformat', 'listoverridestart', 'liststyleid', 'leveloldn',
  'leveltemplateid', 'levelpicture', 'levelprev', 'levelprevspace',
  'levelspace', 'levelnorestart', 'levellegal',
  // Section break alignment & view kind (already handled — listed for inventory).
  'sbkcol', 'sbkeven', 'sbkodd',
  // Word feature flags.
  'enforceprot', 'fittextN', 'newtblstyruls', 'noafcnsttbl', 'nobrkwrptbl',
  // Track-changes-related additional flags.
  'oldas',
  // Highlight flag (already exists as value, but listed).
  'truncatefontheight',
]);
class DocumentBuilder {
  constructor() {
    this.doc = {
      defaults: { char: defaultCharState(), para: defaultParaState() },
      fontTable: new Map(),
      colorTable: [], // first entry is "auto" placeholder
      styles: new Map(),
      lists: new Map(),
      listOverrides: new Map(),
      info: {},
      sections: [],
      defaultLang: 1033,
      defaultTab: 720, // twips, overridden by \deftab
      pageDefaults: defaultSectionState(),
    };

    this.section = this._newSection();
    this.paragraph = null; // current building paragraph
    this.row = null; // current building table row
    this.rowState = defaultRowState();
    this.tableStack = []; // stack of rows being built (for nested tables — limited support)
    this.currentTable = null; // most recent open table

    // State stack: each frame holds char, para, section, dest, etc.
    this.stack = [this._newFrame({
      char: defaultCharState(),
      para: defaultParaState(),
      section: this._cloneSec(this.doc.pageDefaults),
      dest: DEST_BODY,
      ucSkip: 1,
      skipUntilGroupEnd: false,
      starred: false,
    })];

    // Helpers
    this._fontCharsetByIndex = new Map();
    this._currentFontEntryId = null;
    this._currentColor = { r: 0, g: 0, b: 0, set: false };
    this._currentStyleId = null;
    this._currentStyleType = 'paragraph';
    this._currentInfoField = null;
    this._currentInfoText = '';
    this._headerType = null;
    this._headerBlocks = null;
    this._pictState = null;
    this._currentList = null;
    this._currentLevel = null;
    this._listLevelTextBuf = '';
    this._listOverride = null;

    // Pending Unicode skip count when \uN encountered: skip next N bytes / hex bytes
    this._unicodePending = 0;

    // Stack of shape state objects (used by \shpinst → \shptxt to capture
    // floating text frames with their absolute positions).
    this._shapeStack = [];
    this._currentShape = null;
    // Paragraph being built inside the current shape's \shptxt destination.
    this._shapeParagraph = null;

    // Track whether we're inside the document body proper (after first \pard or first content)
    this._sawDocBody = false;
  }

  // ----- frame helpers -----
  _newFrame(init) { return Object.assign({}, init); }
  _cloneSec(s) { return Object.assign({}, s); }
  _top() { return this.stack[this.stack.length - 1]; }
  _ensureParagraph() {
    if (!this.paragraph) {
      const top = this._top();
      this.paragraph = {
        kind: 'paragraph',
        state: cloneState(top.para),
        // Capture the active char state too, so empty paragraphs can be sized
        // off the right font even though they have no runs.
        charState: cloneState(top.char),
        runs: [],
      };
      // Attach any body shapes that were finalized between paragraphs to
      // this fresh one — the shape's \shpbypara anchor is this paragraph's
      // top, and the layout pass renders the shape BEFORE the paragraph
      // text. (Sample_02 page 3/4 image overlay flow.)
      if (this._pendingBodyShapes && this._pendingBodyShapes.length) {
        this.paragraph.precedingShapes = this._pendingBodyShapes;
        this._pendingBodyShapes = null;
      }
    }
    return this.paragraph;
  }
  _commitParagraph() {
    if (!this.paragraph) return;
    // Re-capture paragraph state at commit time. \pard and per-paragraph
    // directives (\fi/\li/\ri/\sa/\qj/\s, etc.) often appear AFTER the first
    // text run is emitted — typical RTF pattern is `{\listtext...}\pard\plain
    // \s38 \fi360 \li-360 ... text \par`. Capturing at the first emit would
    // freeze the indents at style-default values; capturing at commit picks
    // up every override that was applied before \par.
    const top = this._top();
    this.paragraph.state = cloneState(top.para);
    // List paragraphs use whatever \li/\fi the RTF specifies. Word does
    // not silently force "fi = -li" — paragraphs at level 0 in the legal
    // numbered list (s37) emit `\li-360` only and Word renders the label
    // at margin − 24 logical, while level 1 (s38) emits `\fi360\li-360`
    // and renders the label at the margin. The body alignment is still
    // normalized to the list-wide max listTabStop in _normalizeListTabs
    // so "1." and "1.1" share the same body x.
    if (this.paragraph.state.inTable) {
      // paragraphs inside table cells go into the active cell's content, not section.
      // We collect them into row.pendingCellBlocks until \cell.
      this._addCellBlock(this.paragraph);
    } else {
      this.section.blocks.push(this.paragraph);
    }
    this.paragraph = null;
  }
  _addCellBlock(block) {
    if (!this.row) this.row = { kind: 'row', state: Object.assign({}, this.rowState), cells: [], pendingBlocks: [] };
    this.row.pendingBlocks.push(block);
  }
  _newSection() {
    return {
      kind: 'section',
      state: defaultSectionState(),
      blocks: [],
      headers: { default: null, first: null, even: null },
      footers: { default: null, first: null, even: null },
    };
  }

  // Section state setters: write to BOTH the active stack frame and the
  // pending-section's state object, so a value set in a transient group
  // (e.g. `{\sectd\sbknone\cols2 ... }`) is still there when the section
  // commits at \sect / end-of-doc time.
  //
  // We only mirror onto `this.section.state` when the directive is on the
  // main body. \sectd / \pgbrdr* inside `\footerl` or `\header` destinations
  // is part of the header/footer's local section setup; mirroring it would
  // clobber the body's real settings (LibreOffice emits \sectd inside its
  // footer subblocks, which used to wipe page borders).
  _isBodyDest() {
    const top = this._top();
    return top.dest === DEST_BODY;
  }

  _setSectionField(name, value) {
    const top = this._top();
    top.section[name] = value;
    if (this._isBodyDest()) this.section.state[name] = value;
  }

  _setSection(state) {
    const top = this._top();
    top.section = state;
    if (this._isBodyDest()) this.section.state = Object.assign({}, state);
  }

  // \pgbrdrt/l/b/r open one of the four page borders for editing. The
  // returned object is shared between the frame's section, the pending
  // section state (when in the body), and `_currentBorder`, so subsequent
  // \brdrs/\brdrw/\brdrcf mutate all three at once.
  _initPgBorder(field) {
    const top = this._top();
    const obj = top.section[field] || {};
    top.section[field] = obj;
    if (this._isBodyDest()) this.section.state[field] = obj;
    this._currentBorder = obj;
    this._currentPgBorder = obj;
    this._currentPgBorderField = field;
    return obj;
  }

  // ----- parser handler API -----

  groupStart() {
    const cur = this._top();
    const next = this._newFrame({
      char: cloneState(cur.char),
      para: cloneState(cur.para),
      section: this._cloneSec(cur.section),
      dest: cur.dest,
      ucSkip: cur.ucSkip,
      skipUntilGroupEnd: cur.skipUntilGroupEnd,
      starred: false,
      destOwner: false,
    });
    this.stack.push(next);
  }

  // Mark the current frame as the owner of the destination it just set.
  // Cleanup logic in groupEnd should only fire on owner pop.
  _own(dest) {
    const top = this._top();
    top.dest = dest;
    top.destOwner = true;
  }

  groupEnd() {
    if (this.stack.length <= 1) return;
    const popped = this.stack.pop();

    // Math element frames (mathOwner) pop the corresponding node off the
    // math stack so subsequent text in sibling/parent nodes goes to the
    // right place. This must run BEFORE the destOwner gate because math
    // element frames inherit DEST_MATH but are not destination owners
    // themselves — only the outermost moMath/mmath group carries
    // destOwner.
    if (popped.mathOwner) {
      if (this._mathStack && this._mathStack.length > 1) {
        this._mathStack.pop();
      }
    }

    if (!popped.destOwner) return;

    // Destination owner finalization
    if (popped.dest === DEST_FONT && this._currentFontEntryId !== null) {
      this._finalizeFontEntry();
    } else if (popped.dest === DEST_FONT_ALT) {
      // \*\falt closing — attach the captured alt name to the current
      // font entry so resolveFont can prepend it to the CSS chain.
      if (this._fontEntry) {
        this._fontEntry.altName = (this._fontEntryAltName || '').trim() || undefined;
      }
      this._fontEntryAltName = '';
    } else if (popped.dest === DEST_COLORTBL) {
      if (this._currentColor.set) {
        this.doc.colorTable.push({ r: this._currentColor.r, g: this._currentColor.g, b: this._currentColor.b });
        this._currentColor = { r: 0, g: 0, b: 0, set: false };
      }
    } else if (popped.dest === DEST_STYLE && this._currentStyleId !== null) {
      this._finalizeStyleEntry(popped);
    } else if (popped.dest === DEST_INFO_FIELD && this._currentInfoField) {
      this.doc.info[this._currentInfoField] = this._currentInfoText;
      this._currentInfoField = null;
      this._currentInfoText = '';
    } else if (popped.dest === DEST_PICT && this._pictState) {
      this._finalizePicture();
    } else if (popped.dest === DEST_HEADER || popped.dest === DEST_FOOTER) {
      if (this.paragraph && this._headerBlocks) {
        this._headerBlocks.push(this.paragraph);
        this.paragraph = null;
      }
      if (this._headerBlocks) {
        const target = popped.dest === DEST_HEADER ? this.section.headers : this.section.footers;
        const slot = this._headerType || 'default';
        // If the explicit override is empty (just whitespace paragraphs)
        // and we have an inherited footer/header from the prior section,
        // keep the inherited one. Word treats empty redefinitions as
        // "no override" — sample_06 section 2 has an empty \footerr but
        // ref's page 2 still gets section 1's PAGE-number footer.
        const inherited = popped.dest === DEST_HEADER ? this._inheritedHeaders : this._inheritedFooters;
        if (this._hasMeaningfulContent(this._headerBlocks)) {
          target[slot] = this._headerBlocks;
        } else if (inherited && inherited[slot]) {
          target[slot] = inherited[slot];
        } else {
          target[slot] = this._headerBlocks; // empty but no inherited fallback
        }
      }
      this._headerBlocks = null;
      this._headerType = null;
    } else if (popped.dest === DEST_LIST_LEVEL && this._currentLevel) {
      if (this._currentList) {
        this._currentList.levels.push(this._currentLevel);
      }
      this._currentLevel = null;
    } else if (popped.dest === DEST_LIST_LEVEL_TEXT && this._currentLevel) {
      this._currentLevel.text = this._listLevelTextBuf;
      this._listLevelTextBuf = '';
    } else if (popped.dest === DEST_LIST_OVERRIDE) {
      if (this._listOverride) {
        this.doc.listOverrides.set(this._listOverride.id, this._listOverride);
        this._listOverride = null;
      }
    } else if (popped.dest === DEST_LIST && this._currentList) {
      this.doc.lists.set(this._currentList.id, this._currentList);
      this._currentList = null;
    } else if (popped.dest === DEST_SHAPE_TEXT && this._currentShape) {
      // \shptxt group closed — flush any open paragraph into the shape's
      // paragraph list. The DEST_SHAPE pop (one frame above) is what
      // actually finalizes and attaches the shape to its container.
      if (this._shapeParagraph) this._commitShapeParagraph();
    } else if (popped.dest === DEST_NESTED_TABLE_PROPS) {
      // Restore _currentCellInfo so subsequent \clbrdr* (e.g. for the next
      // outer cell) don't keep overwriting the previous one.
      this._currentCellInfo = this._savedCellInfo || null;
      this._savedCellInfo = null;
    } else if (popped.dest === DEST_SHAPE_SP_VALUE) {
      // \sp{\sv value} closed — apply the captured (name,value) pair to the
      // current shape's positioning. Word's RTF emits \shpbxignore/\shpbyignore
      // alongside SP properties posrelh/posrelv; the SP property is the
      // authoritative anchor (1=margin, 2=page, 3=column).
      if (this._currentShape && this._spName) {
        const n = this._spName.trim();
        const v = parseInt((this._spValue || '').trim(), 10);
        if (!Number.isNaN(v)) this._applyShapeSpProp(this._currentShape, n, v);
      }
      this._spName = '';
      this._spValue = '';
    } else if (popped.dest === DEST_SHAPE_SP_NAME) {
      // \sn group closed — name capture done; value follows in a sibling \sv.
    } else if (popped.dest === DEST_SHAPE) {
      // \shpinst group closed — finalize and attach the shape to its
      // surrounding container so the layout pass can render it as an
      // absolutely-positioned floating block.
      this._finalizeShape();
    } else if (popped.dest === DEST_MATH) {
      // Top-level math group closed — flatten the collected expression
      // tree into an inline string and emit as a body text run so the
      // math content shows up inline with the surrounding paragraph.
      const flat = this._flattenMath(this._mathRoot);
      if (flat) {
        const top2 = this._top();
        if (top2 && top2.char) {
          this._appendRun({ kind: 'text', text: flat, charState: cloneState(top2.char) });
        }
      }
      this._mathRoot = null;
      this._mathStack = null;
    }
  }

  controlWord(name, hasArg, arg) {
    const top = this._top();
    if (top.skipUntilGroupEnd) return;

    // Unicode escape: emit codepoint, then arrange to skip next ucSkip bytes/chars
    if (name === 'u' && hasArg) {
      let cp = arg;
      if (cp < 0) cp += 0x10000;
      cp = mapSymbolPua(cp);
      const text = String.fromCodePoint(cp);
      // Route through the destination-aware text handler so \u inside
      // tables/destinations doesn't leak into the body.
      this.text(text);
      this._unicodePending = top.ucSkip;
      return;
    }
    if (name === 'uc' && hasArg) {
      top.ucSkip = arg;
      return;
    }

    // Header table destinations (top-level table introducers). These set the destination.
    switch (name) {
      case 'fonttbl': this._own(DEST_FONTTBL); return;
      case 'colortbl':
        this._own(DEST_COLORTBL);
        // The first ';' inside the colortbl group represents the "auto" entry
        // and is pushed by the text handler. We do not pre-seed an entry here,
        // otherwise \cfN would be off-by-one for every defined color.
        return;
      case 'stylesheet': this._own(DEST_STYLESHEET); return;
      case 'info': this._own(DEST_INFO); return;
      case 'listtable': this._own(DEST_LISTTBL); return;
      case 'listoverridetable': this._own(DEST_LIST_OVERRIDE_TBL); return;
      case 'pict':
        this._own(DEST_PICT);
        this._pictState = {
          format: 'unknown', width: 0, height: 0, scaleX: 100, scaleY: 100,
          goalWidth: 0, goalHeight: 0, hex: '', bin: null,
        };
        return;
    }

    // \nonshppict / \shppict appear with or without the \* prefix in the wild.
    // \nonshppict is the legacy WMF/EMF fallback for the same picture given in
    // the surrounding \shppict; we skip it to avoid both rendering the same
    // image twice and emitting a huge unsupported-format placeholder that
    // displaces real content onto later pages.
    if (name === 'nonshppict') {
      top.starred = false;
      top.skipUntilGroupEnd = true;
      return;
    }
    if (name === 'shppict') {
      top.starred = false;
      top.dest = DEST_BODY;
      return;
    }

    // Star-prefixed destination: \* came earlier; the next control word names the destination.
    if (top.starred) {
      top.starred = false;
      // Some \* destinations we care about:
      if (name === 'fldinst') {
        this._own(DEST_FIELD_INST);
        this._currentFieldInst = '';
        return;
      }
      if (name === 'fldrslt') {
        this._enterFieldResult();
        return;
      }
      if (name === 'shpinst') {
        // Shape — drill in to extract any embedded \pict or \shptxt, but
        // suppress metadata text like shape-type ids. Capture position
        // properties so the layout can render text shapes at their
        // absolute on-page coordinates.
        this._own(DEST_SHAPE);
        this._currentShape = {
          left: 0, right: 0, top: 0, bottom: 0,
          bxColumn: false, byPara: false, bxPage: false, byPage: false,
          bxMargin: false, byMargin: false,
          // \shpwr (default 3 = "in front" = no wrap) and \shpwrk (default 0 = "both sides")
          // — see RTF spec table for wrap modes.
          wrapMode: 3, wrapSide: 0,
          containerDest: this._outerBodyDest(),
          containerHeaderType: this._headerType,
          paragraphs: [],
        };
        this._shapeStack.push(this._currentShape);
        return;
      }
      if (name === 'nesttableprops') {
        // LibreOffice puts the visible cell borders for tables like the
        // QUANTIFICATION grid on sample_01 page 3 inside `\*\nesttableprops`.
        // Route the inner border directives to the OUTER cell's info so the
        // grid renders with a visible frame. We also capture the nested
        // cell's `\trleft`/padding so the layout pass can inset the border
        // — that gap is what makes the reference look like separate boxes
        // rather than a unified grid.
        this._own(DEST_NESTED_TABLE_PROPS);
        this._savedCellInfo = this._currentCellInfo;
        this._currentCellInfo = this._outerCellInfo();
        // Reset the captured nested-frame metrics so we don't carry over a
        // previous cell's offsets into this one.
        if (this._currentCellInfo) {
          this._currentCellInfo.nestedFrame = { trleft: 0, padL: 0, padR: 0, padT: 0, padB: 0 };
        }
        return;
      }
      if (name === 'falt' && top.dest === DEST_FONT) {
        // Inside a fonttbl entry, \*\falt is a fallback-name destination.
        // Capture its text so resolveFont can prepend the alt name to the
        // CSS chain. Outside fonttbl, \falt has no body-level meaning and
        // falls through to the skip below.
        this._own(DEST_FONT_ALT);
        this._fontEntryAltName = '';
        return;
      }
      const nameLc = name.toLowerCase();
      if (MATH_OUTER_DESTS.has(nameLc)) {
        // Enter Office Open Math collection mode. All text inside the
        // group is gathered into the active math node and flattened to
        // an inline string on group close. Inner math elements
        // (mr/mfrac/msup/...) push child nodes via _onMathWord so the
        // structural rendering can introduce separators (e.g., "/" for
        // fractions, "^" for superscript).
        this._own(DEST_MATH);
        this._enterMathRoot();
        return;
      }
      // Math sub-elements ({\*\mfrac ...}, {\*\mr ...}) appear inside an
      // already-open math group. Route them to _onMathWord so the math
      // tree picks them up — without this, KNOWN_SKIP_DESTS would
      // discard their content.
      if (top.dest === DEST_MATH && (MATH_ELEMENT_WORDS.has(nameLc) || MATH_PROP_WORDS.has(nameLc))) {
        return this._onMathWord(nameLc, hasArg, arg);
      }
      if (name === 'panose' || KNOWN_SKIP_DESTS.has(name)) {
        top.skipUntilGroupEnd = true;
        return;
      }
      // Unknown starred destination — skip per RTF spec
      top.skipUntilGroupEnd = true;
      return;
    }
    if (name === '*') {
      top.starred = true;
      return;
    }

    // Non-starred field-result destination. RTF emits \fldrslt without \*
    // around the rendered value of a field — we need to handle it the same
    // way we handle the starred form so a `{\field{\fldinst PAGE}{\fldrslt 2}}`
    // footer doesn't bake the cached page number into the body text.
    if (name === 'fldrslt') {
      this._enterFieldResult();
      return;
    }

    // Dispatch by current destination
    switch (top.dest) {
      case DEST_MATH: return this._onMathWord(name, hasArg, arg);
      case DEST_FONTTBL: return this._onFontTblWord(name, hasArg, arg);
      case DEST_FONT: return this._onFontEntryWord(name, hasArg, arg);
      case DEST_FONT_ALT: return; // text-only destination

      case DEST_COLORTBL: return this._onColorTblWord(name, hasArg, arg);
      case DEST_STYLESHEET: return this._onStylesheetWord(name, hasArg, arg);
      case DEST_STYLE: return this._onStyleEntryWord(name, hasArg, arg);
      case DEST_INFO: return this._onInfoWord(name, hasArg, arg);
      case DEST_INFO_FIELD: return; // ignore control words inside info field
      case DEST_PICT: return this._onPictWord(name, hasArg, arg);
      case DEST_LISTTBL: return this._onListTblWord(name, hasArg, arg);
      case DEST_LIST: return this._onListWord(name, hasArg, arg);
      case DEST_LIST_LEVEL: return this._onListLevelWord(name, hasArg, arg);
      case DEST_LIST_LEVEL_TEXT: return; // text only
      case DEST_LIST_OVERRIDE_TBL: return this._onListOverrideTblWord(name, hasArg, arg);
      case DEST_LIST_OVERRIDE: return this._onListOverrideWord(name, hasArg, arg);
      case DEST_HEADER:
      case DEST_FOOTER: return this._onBodyWord(name, hasArg, arg);
      case DEST_FIELD_INST: return; // ignore field instructions for now
      case DEST_FIELD_RESULT: return this._onBodyWord(name, hasArg, arg);
      case DEST_SHAPE: return this._onShapeWord(name, hasArg, arg);
      case DEST_SHAPE_TEXT: return this._onShapeTextWord(name, hasArg, arg);
      case DEST_NESTED_TABLE_PROPS: return this._onNestedTablePropsWord(name, hasArg, arg);
      case DEST_BODY:
      default: return this._onBodyWord(name, hasArg, arg);
    }
  }

  // Open the field-result destination. If the immediately preceding
  // \fldinst named a dynamic field (currently only PAGE is supported),
  // emit a placeholder run that the layout pass resolves to the live
  // page number and skip the cached static result baked into the RTF.
  _enterFieldResult() {
    const inst = (this._currentFieldInst || '').trim().toUpperCase();
    this._currentFieldInst = '';
    if (/^PAGE\b/.test(inst)) {
      this._appendRun({ kind: 'pageNum', text: '#' });
      this._top().skipUntilGroupEnd = true;
      return;
    }
    this._own(DEST_FIELD_RESULT);
  }

  _applyShapeSpProp(shape, name, value) {
    // posrelv / posrelh = 1 means relative to margin, 2 = page, 3 = column.
    // Word emits \shpb*ignore and relies on these SP properties for the
    // actual anchor. We only apply the SP-property override when the RTF
    // didn't already set an explicit \shpby/bx* flag — Word emits *both*
    // (e.g. \shpbypara alongside posrelv=2) for some shapes, and treating
    // SP-property as authoritative breaks shape #1 in sample_01 where
    // \shpbypara is the actual intended anchor.
    if (name === 'posrelv') {
      if (!shape.byPage && !shape.byMargin && !shape.byPara) {
        if (value === 2) shape.byPage = true;
        else if (value === 1) shape.byMargin = true;
      }
    } else if (name === 'posrelh') {
      if (!shape.bxPage && !shape.bxMargin && !shape.bxColumn) {
        if (value === 2) shape.bxPage = true;
        else if (value === 1) shape.bxMargin = true;
        else if (value === 3) shape.bxColumn = true;
      }
    } else if (name === 'shapeType') {
      // Geometric primitive id — see OOXML ST_ShapeType enum.
      // 1=rectangle, 2=roundRectangle, 3=ellipse, 4=diamond,
      // 5=isocelesTriangle, 9=hexagon, 20=line, 202=textBox.
      shape.shapeType = value;
    } else if (name === 'fillColor') {
      // BGR-packed integer — low byte is R, middle G, high B (per
      // OfficeArt's RGB() macro).
      shape.fillColor = value;
    } else if (name === 'lineColor') {
      shape.lineColor = value;
    } else if (name === 'lineWidth') {
      // Stroke width in EMU (1 EMU = 1/360,000 cm). For canvas drawing,
      // 12700 EMU = 1 pt = 1.33 logical px.
      shape.lineWidth = value;
    } else if (name === 'fFilled') {
      shape.filled = value !== 0;
    } else if (name === 'fLine') {
      shape.lined = value !== 0;
    } else if (name === 'rotation') {
      // Encoded as fixed-point hundredths of a degree clockwise.
      shape.rotation = value / 65536;
    }
  }

  _onShapeWord(name, hasArg, arg) {
    // Inside \*\shpinst — we're hunting for the embedded \pict in the "pib"
    // shape property AND the \shptxt destination for text frames. Most
    // other control words are positioning metadata.
    const sh = this._currentShape;
    if (name === 'pict') {
      this._own(DEST_PICT);
      this._pictState = {
        format: 'unknown', width: 0, height: 0, scaleX: 100, scaleY: 100,
        goalWidth: 0, goalHeight: 0, hex: '', bin: null,
      };
      return;
    }
    if (name === 'sn') {
      // \sp{\sn name} — capture the property name as text in this group.
      this._spName = '';
      this._own(DEST_SHAPE_SP_NAME);
      return;
    }
    if (name === 'sv') {
      // \sp{\sv value} — capture the property value text. Some sv groups
      // contain \pict (image data), but for the position properties we care
      // about (posrelv, posrelh, etc.) the value is plain numeric text.
      this._spValue = '';
      this._own(DEST_SHAPE_SP_VALUE);
      return;
    }
    if (sh) {
      // Shape positioning. Coordinates are in twips relative to the anchor
      // chosen by \shpbxcolumn/\shpbypara/etc.
      switch (name) {
        case 'shpleft':   if (hasArg) sh.left = arg;   return;
        case 'shpright':  if (hasArg) sh.right = arg;  return;
        case 'shptop':    if (hasArg) sh.top = arg;    return;
        case 'shpbottom': if (hasArg) sh.bottom = arg; return;
        case 'shpbxcolumn': sh.bxColumn = true; return;
        case 'shpbxpage':   sh.bxPage = true;   return;
        case 'shpbxignore': return;
        case 'shpbypara':   sh.byPara = true;   return;
        case 'shpbypage':   sh.byPage = true;   return;
        case 'shpbyignore': return;
        case 'shpz':        return;
        case 'shpwr':       if (hasArg) sh.wrapMode = arg; return;
        case 'shpwrk':      if (hasArg) sh.wrapSide = arg; return;
      }
    }
    if (name === 'shptxt') {
      // \shptxt opens a sub-document containing the shape's text frame
      // contents. Switch to the shape-text destination so subsequent text
      // / \par events accumulate into the shape's own paragraph list
      // rather than the surrounding header/body.
      this._own(DEST_SHAPE_TEXT);
      this._shapeParagraph = null;
      // Re-seed the per-frame paragraph state: a shape-text destination
      // starts with its own \pard-equivalent default.
      const top = this._top();
      top.para = defaultParaState();
      return;
    }
    // Any other control word inside a shape (fill, etc.) — ignore
  }

  // Walk up the frame stack to find the surrounding "body-like" destination
  // (header, footer, or body) so the shape knows where to attach when its
  // text frame closes.
  _outerBodyDest() {
    for (let i = this.stack.length - 1; i >= 0; i--) {
      const d = this.stack[i].dest;
      if (d === DEST_HEADER || d === DEST_FOOTER) return d;
      if (d === DEST_BODY) return DEST_BODY;
    }
    return DEST_BODY;
  }

  // ---- Shape-text helpers ----

  // Append a run to the shape's currently-building paragraph.
  _appendShapeRun(run) {
    if (!this._shapeParagraph) this._ensureShapeParagraph();
    const para = this._shapeParagraph;
    const last = para.runs[para.runs.length - 1];
    if (last && last.kind === 'text' && run.kind === 'text' && sameCharState(last.charState, run.charState)) {
      last.text += run.text;
      return;
    }
    para.runs.push(run);
  }

  _ensureShapeParagraph() {
    if (this._shapeParagraph) return;
    const top = this._top();
    this._shapeParagraph = {
      kind: 'paragraph',
      state: cloneState(top.para),
      charState: cloneState(top.char),
      runs: [],
    };
  }

  _commitShapeParagraph() {
    if (!this._currentShape) return;
    if (!this._shapeParagraph) {
      const top = this._top();
      this._shapeParagraph = {
        kind: 'paragraph',
        state: cloneState(top.para),
        charState: cloneState(top.char),
        runs: [],
      };
    }
    // Capture state at commit time (paragraph directives often appear after
    // the first text run — same rule as the body builder).
    const top = this._top();
    this._shapeParagraph.state = cloneState(top.para);
    this._currentShape.paragraphs.push(this._shapeParagraph);
    this._shapeParagraph = null;
  }

  // Pop the current shape and attach it (if it has any text content) to
  // its surrounding container. The layout pass renders shape blocks at
  // their absolute (shp{left,right,top,bottom}) coordinates.
  _finalizeShape() {
    if (!this._currentShape) {
      this._shapeStack.pop();
      this._currentShape = this._shapeStack[this._shapeStack.length - 1] || null;
      return;
    }
    const sh = this._currentShape;
    this._shapeStack.pop();
    this._currentShape = this._shapeStack[this._shapeStack.length - 1] || null;
    // A shape is empty (no content to render) when it has none of: text
    // paragraphs, an embedded image, or a geometric primitive that gives
    // it visual presence (rectangle, oval, line, text-box outline, etc.).
    const hasPrimitive = sh.shapeType !== undefined &&
      (sh.filled || sh.lined !== false || sh.shapeType === 202);
    if (!sh.paragraphs.length && !sh.image && !hasPrimitive) return;
    const block = {
      kind: 'shape',
      left: sh.left, right: sh.right, top: sh.top, bottom: sh.bottom,
      bxColumn: sh.bxColumn, byPara: sh.byPara, bxPage: sh.bxPage, byPage: sh.byPage,
      bxMargin: sh.bxMargin, byMargin: sh.byMargin,
      wrapMode: sh.wrapMode, wrapSide: sh.wrapSide,
      containerDest: sh.containerDest,
      paragraphs: sh.paragraphs,
      image: sh.image || null,
      // Geometric primitive properties (used when no image/paragraphs).
      shapeType: sh.shapeType,
      fillColor: sh.fillColor,
      lineColor: sh.lineColor,
      lineWidth: sh.lineWidth,
      filled: sh.filled !== false,
      lined: sh.lined !== false,
      rotation: sh.rotation,
    };
    if (sh.containerDest === DEST_HEADER || sh.containerDest === DEST_FOOTER) {
      // Attach to the header/footer being built, even if its destination
      // frame already popped — _headerBlocks is still the active list.
      if (this._headerBlocks) {
        this._headerBlocks.push(block);
      } else {
        const target = sh.containerDest === DEST_HEADER ? this.section.headers : this.section.footers;
        const slot = sh.containerHeaderType || 'default';
        const list = target[slot] || (target[slot] = []);
        list.push(block);
      }
    } else {
      // Body shape: attach to the surrounding paragraph (the one currently
      // open in the body flow). The shape's \shpbypara anchor is that
      // paragraph's top, and the layout pass renders the shape BEFORE the
      // paragraph's text so following content flows below the image.
      if (this.paragraph) {
        if (!this.paragraph.precedingShapes) this.paragraph.precedingShapes = [];
        this.paragraph.precedingShapes.push(block);
      } else {
        // No paragraph open — queue for the next one.
        if (!this._pendingBodyShapes) this._pendingBodyShapes = [];
        this._pendingBodyShapes.push(block);
      }
      // Keep on section.shapes for reference (currently unused).
      if (!this.section.shapes) this.section.shapes = [];
      this.section.shapes.push(block);
    }
  }

  // ---- Math (Office Open Math) collection ----

  // Initialize the math expression tree at the start of a top-level math
  // destination (\moMath, \mmath, etc.). Subsequent math element words
  // push child nodes onto _mathStack; text inside leaf elements is
  // appended to whatever node is on top.
  _enterMathRoot() {
    this._mathRoot = { kind: 'root', children: [], text: '' };
    this._mathStack = [this._mathRoot];
  }

  // Dispatch math control words while inside DEST_MATH. Most words push a
  // new child node onto the active math node, route subsequent text/words
  // into that node until the group ends, then pop. Property words
  // (mfpr/msuppr/...) and pure attributes are no-ops.
  _onMathWord(name, hasArg, arg) {
    const top = this._top();
    if (top.skipUntilGroupEnd) return;
    const nameLc = name.toLowerCase();
    // Parameter properties — ignore (they describe styling we don't
    // currently visualize, e.g. fraction-bar style or accent character).
    if (MATH_PROP_WORDS.has(nameLc)) {
      top.skipUntilGroupEnd = true;
      return;
    }
    // Math element opener: push a new node and mark this frame as the
    // node's owner so groupEnd pops it cleanly.
    if (MATH_ELEMENT_WORDS.has(nameLc)) {
      const node = { kind: nameLc, children: [], text: '' };
      const parent = this._mathStack[this._mathStack.length - 1];
      if (parent) parent.children.push(node);
      this._mathStack.push(node);
      top.mathOwner = true;
      return;
    }
    // Other character / formatting words inside math — treat as the same
    // body-level handlers (e.g. \i italics, \b bold, \cf color) so the
    // active char state stays in sync. We keep the math destination so
    // the parent's _onMathWord still receives subsequent words.
    this._onBodyWord(name, hasArg, arg);
  }

  // Recursively flatten the math tree to an inline string. Structural
  // elements introduce readable separators: fractions render as
  // "(num)/(den)", scripts as "x^(sup)" / "x_(sub)", radicals as
  // "√(content)". Property nodes contribute nothing because their text
  // collection was suppressed in _onMathWord.
  _flattenMath(node) {
    if (!node) return '';
    const k = node.kind;
    if (!node.children || !node.children.length) return node.text || '';
    const parts = node.children.map((c) => this._flattenMath(c));
    switch (k) {
      case 'mfrac':
        // Children are typically [mnum, mden]; emit "(a)/(b)" using
        // whichever children we got (some emitters skip the wrappers).
        return parts.length >= 2
          ? `(${parts[0]})/(${parts[1]})`
          : parts.join('/');
      case 'mnum':
      case 'mden':
      case 'me':
      case 'mr':
      case 'mt':
      case 'mtext':
      case 'mn':
      case 'mlit':
      case 'mchr':
      case 'mfname':
        return parts.join('') + (node.text || '');
      case 'msup':
      case 'mssup':
        return parts.length >= 2 ? `${parts[0]}^(${parts[1]})` : parts.join('^');
      case 'msub':
      case 'mssub':
        return parts.length >= 2 ? `${parts[0]}_(${parts[1]})` : parts.join('_');
      case 'mssubsup':
      case 'msubsup':
        return parts.length >= 3 ? `${parts[0]}_(${parts[1]})^(${parts[2]})` : parts.join('');
      case 'mrad':
        // Radical: optional degree as parts[0], radicand as parts[parts.length-1].
        if (parts.length >= 2) return `${parts[0] || ''}√(${parts[parts.length - 1]})`;
        return `√(${parts.join('')})`;
      case 'mdeg':
        return parts.join('');
      case 'mnary':
        return parts.join('');
      case 'mlim':
        return parts.length >= 2 ? `lim_(${parts[1]}) ${parts[0]}` : parts.join('');
      case 'mfunc':
      case 'mfname':
        return parts.join('');
      case 'mgroupchr':
      case 'mbar':
      case 'macc':
      case 'mphant':
      case 'mbox':
      case 'mborderbox':
      case 'meqarr':
      case 'md':
        return parts.join('');
      case 'mbegchr':
        return parts.join('') || '(';
      case 'mendchr':
        return parts.join('') || ')';
      case 'msepchr':
        return parts.join('') || ',';
      case 'mscr':
        return parts.join('');
      case 'momath':
      case 'momathpara':
      case 'mmath':
      case 'mmathpara':
      case 'root':
      default:
        return parts.join('') + (node.text || '');
    }
  }

  // Shape-text destination word handler — accepts the same character /
  // paragraph formatting words as the body, but emits runs into the
  // shape's local paragraph list rather than the surrounding container.
  _onShapeTextWord(name, hasArg, arg) {
    const top = this._top();
    // Most formatting/structure verbs route through _onBodyWord with the
    // emit / end functions stashed on `this`. We temporarily redirect them
    // to the shape-text helpers so \par etc. land in the right place.
    const savedEmit = this._emitText;
    const savedEndPara = this._endParagraph;
    const savedAppend = this._appendRun;
    this._emitText = (text) => {
      if (!text) return;
      if (!this._shapeParagraph) this._ensureShapeParagraph();
      this._appendShapeRun({ kind: 'text', text, charState: cloneState(top.char) });
    };
    this._appendRun = (run) => {
      if (!this._shapeParagraph) this._ensureShapeParagraph();
      this._appendShapeRun({ ...run, charState: cloneState(top.char) });
    };
    this._endParagraph = () => this._commitShapeParagraph();
    try {
      this._onBodyWord(name, hasArg, arg);
    } finally {
      this._emitText = savedEmit;
      this._endParagraph = savedEndPara;
      this._appendRun = savedAppend;
    }
  }

  controlSymbol(ch) {
    const top = this._top();
    if (top.skipUntilGroupEnd) return;
    switch (ch) {
      case '\\': case '{': case '}':
        this._emitText(ch); return;
      case '~': this._emitText(NBSP); return;
      case '-': this._emitText(OPT_HYPHEN); return;
      case '_': this._emitText(NB_HYPHEN); return;
      case '*':
        // marks the next word as a starred destination
        top.starred = true;
        return;
      case '\n': case '\r':
        // \⏎ acts as \par
        this._endParagraph();
        return;
      case ':':
        // subentry separator in index entries — ignore
        return;
      default:
        // unknown control symbol — ignore
        return;
    }
  }

  text(s) {
    const top = this._top();
    if (top.skipUntilGroupEnd) return;
    if (this._unicodePending > 0) {
      // skip ucSkip characters of "compatibility" text following \u
      const skip = Math.min(this._unicodePending, s.length);
      s = s.slice(skip);
      this._unicodePending -= skip;
      if (s.length === 0) return;
    }
    switch (top.dest) {
      case DEST_FONT:
        // font name is the text content of the font entry, ending at ';'
        {
          const semi = s.indexOf(';');
          if (semi >= 0) {
            this._fontEntryName += s.slice(0, semi);
            // anything after the semicolon is technically unexpected here, ignore
          } else {
            this._fontEntryName += s;
          }
        }
        return;
      case DEST_FONT_ALT:
        // Alt-name (\*\falt) text — accumulate until the destination closes.
        {
          const semi = s.indexOf(';');
          this._fontEntryAltName += semi >= 0 ? s.slice(0, semi) : s;
        }
        return;
      case DEST_COLORTBL:
        // text inside colortbl is just semicolons separating color entries
        for (let i = 0; i < s.length; i++) {
          if (s.charCodeAt(i) === 0x3B /* ; */) {
            this.doc.colorTable.push(this._currentColor.set
              ? { r: this._currentColor.r, g: this._currentColor.g, b: this._currentColor.b }
              : null);
            this._currentColor = { r: 0, g: 0, b: 0, set: false };
          }
        }
        return;
      case DEST_STYLE:
        // style name ends at ';'
        {
          const semi = s.indexOf(';');
          if (semi >= 0) {
            this._styleNameBuf += s.slice(0, semi);
          } else {
            this._styleNameBuf += s;
          }
        }
        return;
      case DEST_INFO_FIELD:
        this._currentInfoText += s;
        return;
      case DEST_MATH:
        // Text inside math (typically inside \mr or \mt) is appended to the
        // active math node so it joins its siblings in the order RTF emits
        // them. The text() handler is the SAME for any math leaf — \mr/\mt/
        // \mn — because the parser treats those as plain text destinations.
        if (this._mathStack && this._mathStack.length) {
          const node = this._mathStack[this._mathStack.length - 1];
          node.text = (node.text || '') + s;
        }
        return;
      case DEST_PICT:
        // hex bytes of image
        if (this._pictState) this._pictState.hex += s.replace(/\s+/g, '');
        return;
      case DEST_LIST_LEVEL_TEXT:
        this._listLevelTextBuf += s;
        return;
      case DEST_FIELD_INST:
        // Accumulate the field instruction text (e.g., "PAGE", "TIME",
        // "HYPERLINK url") so we can decide what to do when fldrslt opens.
        this._currentFieldInst = (this._currentFieldInst || '') + s;
        return;
      case DEST_SHAPE_TEXT:
        if (!this._shapeParagraph) this._ensureShapeParagraph();
        this._appendShapeRun({ kind: 'text', text: s, charState: cloneState(top.char) });
        return;
      case DEST_SHAPE_SP_NAME:
        this._spName = (this._spName || '') + s;
        return;
      case DEST_SHAPE_SP_VALUE:
        this._spValue = (this._spValue || '') + s;
        return;
      case DEST_BODY:
      case DEST_HEADER:
      case DEST_FOOTER:
      case DEST_FIELD_RESULT:
        this._emitText(s);
        return;
      default:
        return;
    }
  }

  hexByte(byte) {
    const top = this._top();
    if (top.skipUntilGroupEnd) return;
    if (this._unicodePending > 0) {
      this._unicodePending--;
      return;
    }
    if (top.dest === DEST_PICT) {
      const hex = byte.toString(16).padStart(2, '0');
      if (this._pictState) this._pictState.hex += hex;
      return;
    }
    // Determine codepage based on current font's charset, fall back to 1252
    const fi = top.char.fontIndex;
    const cp = this._fontCharsetByIndex.get(fi) ?? 1252;
    const cu = decodeByte(byte, cp);
    // Route through text() so destination dispatch (font name, list level
    // text, etc.) applies — without this, \'00-style hex bytes inside
    // \leveltext leak into body paragraphs as control-character glyphs.
    this.text(String.fromCodePoint(cu));
  }

  bin(bytes) {
    const top = this._top();
    if (top.dest === DEST_PICT && this._pictState) {
      // store binary
      this._pictState.bin = bytes;
    }
    // Otherwise ignore
  }

  end() {
    if (this.paragraph) this._commitParagraph();
    // Same merge rule as _endSection: directives written via _setSectionField
    // win over whatever is left on the (potentially shallow) top frame.
    this.section.state = Object.assign({}, this._top().section, this.section.state);
    // Only push the current section if it has content or no sections yet
    if (this.section.blocks.length > 0 || this.doc.sections.length === 0) {
      this.doc.sections.push(this.section);
    }
    this._normalizeListTabs();
    return this.doc;
  }

  // Word lays out every paragraph in a multi-level numbered list with the
  // body at the same x — "1.", "1.1", "2.", "2.1" all line up vertically
  // even though "1." has a shorter label than "1.1". The label-to-body tab
  // is sized to clear the WIDEST level's label, so we walk the document,
  // find each list's maximum listTabStop across all its paragraphs, and
  // raise smaller per-paragraph values to that max. Paragraphs that
  // legitimately have a larger listTabStop (deeper levels) keep theirs.
  _normalizeListTabs() {
    const maxByList = new Map();
    const visit = (block, fn) => {
      if (block.kind === 'paragraph') fn(block);
      else if (block.kind === 'table') {
        for (const row of block.rows || []) {
          for (const cell of row.cells || []) {
            for (const inner of cell.blocks || []) visit(inner, fn);
          }
        }
      }
    };
    const collect = (p) => {
      const lsId = p.state.listId;
      const tab = p.state.listTabStop;
      if (!lsId || typeof tab !== 'number') return;
      const cur = maxByList.get(lsId);
      if (cur === undefined || tab > cur) maxByList.set(lsId, tab);
    };
    const apply = (p) => {
      const lsId = p.state.listId;
      if (!lsId) return;
      const m = maxByList.get(lsId);
      if (typeof m === 'number' && (typeof p.state.listTabStop !== 'number' || p.state.listTabStop < m)) {
        p.state.listTabStop = m;
      }
    };
    for (const sec of this.doc.sections) for (const blk of sec.blocks) visit(blk, collect);
    for (const sec of this.doc.sections) for (const blk of sec.blocks) visit(blk, apply);
  }

  build() {
    return this.doc;
  }

  // ---- Body content handler ----

  _onBodyWord(name, hasArg, arg) {
    const top = this._top();

    // Non-starred destinations that can appear in body context. Each opens
    // a sub-group whose content shouldn't render in-flow. \footnote is the
    // canonical case ({\footnote \chftn body...} after a footnote
    // reference superscript). Others (\falt, \pntext) we route to skip too.
    if (name === 'footnote' || name === 'falt' || name === 'pntext' ||
        name === 'pnseclvl' || name === 'pntxta' || name === 'pntxtb' ||
        name === 'mmath' || name === 'macc' || name === 'maccpr' ||
        name === 'maln' || name === 'malnscr' || name === 'mbar' ||
        name === 'mbox' || name === 'meqarr' || name === 'mfraction' ||
        name === 'mfunc' || name === 'mgroupchr' || name === 'mlim' ||
        name === 'mmatrix' || name === 'mnary' || name === 'mphant' ||
        name === 'mrad' || name === 'mscript' || name === 'msub' ||
        name === 'msup' || name === 'mssub' || name === 'mssup' ||
        name === 'mssubsup' || name === 'mtext' || name === 'momath' ||
        name === 'momathpara' || name === 'momathparapr' || name === 'mmathpr' ||
        name === 'mr' || name === 'mctrlpr' || name === 'me' || name === 'md') {
      top.skipUntilGroupEnd = true;
      return;
    }

    // Character formatting
    switch (name) {
      case 'plain': top.char = defaultCharState(); return;
      case 'b': top.char.bold = !hasArg || arg !== 0; return;
      case 'i': top.char.italic = !hasArg || arg !== 0; return;
      case 'ul': top.char.underline = !hasArg || arg !== 0; return;
      case 'ulnone': top.char.underline = false; return;
      case 'uld': case 'uldash': case 'uldb': case 'ulth': case 'ulw': case 'ulwave':
        top.char.underline = true; return;
      case 'strike': top.char.strike = !hasArg || arg !== 0; return;
      case 'striked': top.char.strike = !hasArg || arg !== 0; return;
      case 'super': top.char.superscript = true; top.char.subscript = false; return;
      case 'sub': top.char.subscript = true; top.char.superscript = false; return;
      case 'nosupersub': top.char.superscript = false; top.char.subscript = false; return;
      case 'fs': if (hasArg) top.char.fontSize = arg; return;
      // \fsmilliN — font size in milli-half-points per RTF spec. We
      // honor it ONLY when it's within rounding of the prior \fs (a
      // precision adjustment for sub-half-point sizes), and ignore it
      // when it differs wildly. Sample_11's \fs42\fsmilli21333 case is
      // a macOS Cocoa-RTF quirk where \fsmilli is half what \fs is,
      // and Word renders \fs (= 21pt) as the source of truth. Without
      // this guard, our render uses 10.7pt where Word uses 21pt — a
      // 2× font size error that puts content on the wrong pages.
      case 'fsmilli':
        if (hasArg) {
          const mhp = arg / 1000;
          const cur = top.char.fontSize;
          if (cur === undefined || Math.abs(cur - mhp) <= 2) {
            top.char.fontSize = mhp;
          }
        }
        return;
      case 'f': if (hasArg) top.char.fontIndex = arg; return;
      case 'cf': if (hasArg) top.char.foreColor = arg; return;
      case 'cb': case 'chcbpat': if (hasArg) top.char.backColor = arg; return;
      case 'highlight': if (hasArg) top.char.highlight = arg; return;
      case 'caps': top.char.allcaps = !hasArg || arg !== 0; return;
      case 'scaps': top.char.smallcaps = !hasArg || arg !== 0; return;
      case 'v': top.char.hidden = !hasArg || arg !== 0; return;
      case 'expnd': case 'expndtw': if (hasArg) top.char.charSpacing = arg; return;
      case 'cs':
        if (hasArg) {
          top.char.style = arg;
          const cs2 = this.doc.styles.get(arg);
          if (cs2 && cs2.type === 'character') {
            Object.assign(top.char, cs2.char);
            top.char.style = arg;
          }
        }
        return;

      // Paragraph formatting
      case 'pard':
        top.para = defaultParaState();
        this._listTabPending = false;
        this._listTabFromStyle = false;
        return;
      case 'ql': top.para.align = 'left'; return;
      case 'qr': top.para.align = 'right'; return;
      case 'qc': top.para.align = 'center'; return;
      case 'qj': top.para.align = 'justify'; return;
      // Frame positioning: \posxc/\posxr/\posxl/\posxi/\posxo set the
      // horizontal anchor of a positioned text frame. We don't render
      // the frame as such, so collapse the frame's effective alignment
      // onto the paragraph itself — \posxc paragraphs (e.g. sample_06's
      // PAGE-number footer) end up centered, matching what Word draws.
      case 'posxc': top.para.align = 'center'; return;
      case 'posxr': case 'posxo': top.para.align = 'right'; return;
      case 'posxl': case 'posxi': top.para.align = 'left'; return;
      case 'li': if (hasArg) top.para.indentLeft = arg; return;
      case 'ri': if (hasArg) top.para.indentRight = arg; return;
      case 'fi': if (hasArg) top.para.indentFirst = arg; return;
      case 'sb': if (hasArg) top.para.spaceBefore = arg; return;
      case 'sa': if (hasArg) top.para.spaceAfter = arg; return;
      case 'sl': if (hasArg) top.para.lineSpacing = arg; return;
      case 'slmult': top.para.lineSpacingMultiple = !hasArg || arg !== 0; return;
      case 'tx':
        if (hasArg) {
          top.para.tabStops.push({ pos: arg, kind: 'left' });
          // \jclisttab marks the *next* \tx as the list-tab position. Word
          // uses this stop preferentially when a list paragraph has its
          // first \tab — otherwise our smallest-stop heuristic picks up
          // some unrelated tab and the bullet/text gap renders too tight.
          // Only the first explicit \jclisttab\tx in the paragraph wins:
          // Word emits noisy duplicates like
          //   `\jclisttab\tx432\jclisttab\tx900`
          // and it's the first one that drives label→body alignment.
          // (The first one is also allowed to overwrite a value inherited
          // from the paragraph style — `_listTabFromStyle` flag.)
          if (this._listTabPending) {
            if (this._listTabFromStyle || typeof top.para.listTabStop !== 'number') {
              top.para.listTabStop = arg;
              this._listTabFromStyle = false;
            }
            this._listTabPending = false;
          }
        }
        return;
      case 'jclisttab': this._listTabPending = true; return;
      case 'tqr': /* next \tx is right tab */ this._nextTabKind = 'right'; return;
      case 'tqc': this._nextTabKind = 'center'; return;
      case 'tqdec': this._nextTabKind = 'decimal'; return;
      case 'keepn': top.para.keepNext = true; return;
      case 'keep': top.para.keepLines = true; return;
      case 'pagebb': top.para.pageBreakBefore = true; return;
      case 's':
        if (hasArg) {
          top.para.style = arg;
          const ps = this.doc.styles.get(arg);
          if (ps && ps.type === 'paragraph') {
            // Word's quirk: applying a paragraph style does NOT inherit
            // \fi from the style. The paragraph's first-line indent stays
            // at the \pard default (0) unless the paragraph itself sets
            // \fi. Verified against sample_06: style s37 (Legal3_L1) has
            // \fi-720\li720, but Word renders s37 paragraphs with fi=0
            // (label at \margl + \li, not \margl + \li + style.fi).
            const styleFi = top.para.indentFirst;
            Object.assign(top.para, ps.para);
            top.para.indentFirst = styleFi;
            Object.assign(top.char, ps.char);
            top.para.style = arg;
            // The style may have set listTabStop; remember so the first
            // explicit \jclisttab\tx in the paragraph still wins over it.
            if (typeof ps.para.listTabStop === 'number') this._listTabFromStyle = true;
          }
        }
        return;
      case 'rtlpar': top.para.rightToLeft = true; return;
      case 'ltrpar': top.para.rightToLeft = false; return;
      case 'cbpat': case 'cbpatN': if (hasArg) top.para.shading = arg; return;
      case 'brdrt': top.para.borderTop = top.para.borderTop || {}; this._currentBorder = top.para.borderTop; return;
      case 'brdrb': top.para.borderBottom = top.para.borderBottom || {}; this._currentBorder = top.para.borderBottom; return;
      case 'brdrl': top.para.borderLeft = top.para.borderLeft || {}; this._currentBorder = top.para.borderLeft; return;
      case 'brdrr': top.para.borderRight = top.para.borderRight || {}; this._currentBorder = top.para.borderRight; return;
      case 'brdrs': if (this._currentBorder) this._currentBorder.style = 'single'; return;
      case 'brdrdb': if (this._currentBorder) this._currentBorder.style = 'double'; return;
      case 'brdrth': if (this._currentBorder) this._currentBorder.style = 'thick'; return;
      case 'brdrw': if (this._currentBorder && hasArg) this._currentBorder.width = arg; return;
      case 'brdrcf': if (this._currentBorder && hasArg) this._currentBorder.color = arg; return;
      case 'brdrnone':
        if (this._currentBorder) this._currentBorder.style = 'none';
        this._currentBorder = null;
        return;
      case 'brsp':
        // Border spacing — gap between text and border in twips. Applies to
        // paragraph-level (\brdrt/b/l/r) borders when one is defined; the
        // page-border path below handles \brsp scoped to \*\pgbrdr*.
        // Fall through to the page-border handler when no paragraph
        // border was set so we don't shadow it.
        if (hasArg && top.para && (top.para.borderTop || top.para.borderBottom || top.para.borderLeft || top.para.borderRight)) {
          if (top.para.borderTop) top.para.borderTop.spacing = arg;
          if (top.para.borderBottom) top.para.borderBottom.spacing = arg;
          if (top.para.borderLeft) top.para.borderLeft.spacing = arg;
          if (top.para.borderRight) top.para.borderRight.spacing = arg;
          return;
        }
        if (this._currentPgBorder && hasArg) {
          this._currentPgBorder.spacing = arg;
          this._setSectionField(this._currentPgBorderField, this._currentPgBorder);
        }
        return;
      case 'brdrdash':
        if (this._currentBorder) this._currentBorder.style = 'dashed'; return;
      case 'brdrdot':
        if (this._currentBorder) this._currentBorder.style = 'dotted'; return;
      case 'brdrdashd':
        if (this._currentBorder) this._currentBorder.style = 'dashdot'; return;
      case 'brdrdashdd':
        if (this._currentBorder) this._currentBorder.style = 'dashdotdot'; return;
      case 'brdrwavy':
        if (this._currentBorder) this._currentBorder.style = 'wavy'; return;
      case 'brdrtriple':
        if (this._currentBorder) this._currentBorder.style = 'triple'; return;
      case 'brdrhair':
        if (this._currentBorder) this._currentBorder.style = 'hair'; return;

      // Paragraph end / breaks
      case 'par': this._endParagraph(); return;
      case 'line':
        // Soft line break: emit a special run
        this._appendRun({ kind: 'br', text: '' });
        return;
      case 'page':
        // hard page break
        this._appendRun({ kind: 'pageBreak', text: '' });
        return;
      case 'sect': this._endSection(); return;
      case 'sectd':
        top.section = this._cloneSec(this.doc.pageDefaults);
        this._setSection(top.section);
        return;
      case 'tab': this._appendRun({ kind: 'tab', text: '\t' }); return;

      // Punctuation / glyph-substitution control words. These are emitted
      // by Word/LibreOffice instead of literal characters so the RTF
      // remains 7-bit clean. Each maps to a single Unicode codepoint.
      case 'emdash': this._emitText(EM_DASH); return;
      case 'endash': this._emitText(EN_DASH); return;
      case 'lquote': this._emitText(LEFT_QUOTE); return;
      case 'rquote': this._emitText(RIGHT_QUOTE); return;
      case 'ldblquote': this._emitText(LEFT_DQUOTE); return;
      case 'rdblquote': this._emitText(RIGHT_DQUOTE); return;
      case 'bullet': this._emitText(BULLET); return;
      case 'enspace': this._emitText('\u2002'); return;
      case 'emspace': this._emitText('\u2003'); return;
      case 'qmspace': this._emitText('\u2005'); return;
      case 'zwnj': this._emitText('\u200C'); return;
      case 'zwj': this._emitText('\u200D'); return;

      // Section / page setup. Each property is also mirrored onto
      // this.section.state via _setSectionField so the value survives once
      // the stack frame that emitted the directive is popped — RTF often
      // sets \sectd\sbknone\cols2 inside a transient group that closes
      // before the next \sect commits.
      case 'deftab': if (hasArg) this.doc.defaultTab = arg; return;
      case 'paperw': if (hasArg) { this._setSectionField('pageWidth', arg); this.doc.pageDefaults.pageWidth = arg; } return;
      case 'paperh': if (hasArg) { this._setSectionField('pageHeight', arg); this.doc.pageDefaults.pageHeight = arg; } return;
      case 'margl': if (hasArg) { this._setSectionField('marginLeft', arg); this.doc.pageDefaults.marginLeft = arg; } return;
      case 'margr': if (hasArg) { this._setSectionField('marginRight', arg); this.doc.pageDefaults.marginRight = arg; } return;
      case 'margt': if (hasArg) { this._setSectionField('marginTop', arg); this.doc.pageDefaults.marginTop = arg; } return;
      case 'margb': if (hasArg) { this._setSectionField('marginBottom', arg); this.doc.pageDefaults.marginBottom = arg; } return;
      // Section-level margin overrides take precedence over page-level
      // \margl/\margr/\margt/\margb for the section that declares them.
      // LibreOffice and Word both emit `\marglsxn` etc. on multi-column
      // sections to widen/narrow the column block independently of the
      // document's page margin.
      case 'marglsxn': if (hasArg) this._setSectionField('marginLeft', arg); return;
      case 'margrsxn': if (hasArg) this._setSectionField('marginRight', arg); return;
      case 'margtsxn': if (hasArg) this._setSectionField('marginTop', arg); return;
      case 'margbsxn': if (hasArg) this._setSectionField('marginBottom', arg); return;
      case 'pgwsxn': if (hasArg) this._setSectionField('pageWidth', arg); return;
      case 'pghsxn': if (hasArg) this._setSectionField('pageHeight', arg); return;
      case 'cols': if (hasArg) this._setSectionField('cols', arg); return;
      case 'colsx': if (hasArg) this._setSectionField('colSpacing', arg); return;
      case 'titlepg': this._setSectionField('titlePage', true); return;
      case 'headery': if (hasArg) this._setSectionField('headerY', arg); return;
      case 'footery': if (hasArg) this._setSectionField('footerY', arg); return;

      // Section break kind. \sbknone is the only one we treat specially:
      // it means "no break between this section and the previous one". The
      // others (sbkpage default, sbkcol, sbkeven, sbkodd) all mean "new page"
      // from our perspective — we don't model alignment to even/odd pages.
      case 'sbknone': this._setSectionField('breakKind', 'none'); return;
      case 'sbkpage': this._setSectionField('breakKind', 'page'); return;
      case 'sbkcol': this._setSectionField('breakKind', 'col'); return;
      case 'sbkeven': this._setSectionField('breakKind', 'page'); return;
      case 'sbkodd': this._setSectionField('breakKind', 'page'); return;

      // Page borders. \pgbrdrt/l/b/r open one of the four edges as the
      // "current border", then subsequent \brdrs/\brdrw/\brdrcf/\brsp set its
      // properties. \pgbrdrhead/foot/opt are layout flags we don't need to
      // model beyond noting their presence.
      case 'pgbrdrt': this._currentPgBorder = this._initPgBorder('pgBorderTop'); return;
      case 'pgbrdrl': this._currentPgBorder = this._initPgBorder('pgBorderLeft'); return;
      case 'pgbrdrb': this._currentPgBorder = this._initPgBorder('pgBorderBottom'); return;
      case 'pgbrdrr': this._currentPgBorder = this._initPgBorder('pgBorderRight'); return;
      case 'brsp': if (this._currentPgBorder && hasArg) { this._currentPgBorder.spacing = arg; this._setSectionField(this._currentPgBorderField, this._currentPgBorder); } return;
      case 'pgbrdrhead': case 'pgbrdrfoot': case 'pgbrdropt': return;

      // Headers / footers (start a destination)
      case 'header': case 'headerl': case 'headerr': case 'headerf':
        if (this.paragraph) this._commitParagraph();
        this._own(DEST_HEADER);
        this._headerType = ({ header: 'default', headerl: 'default', headerr: 'default', headerf: 'first' })[name] || 'default';
        this._headerBlocks = [];
        return;
      case 'footer': case 'footerl': case 'footerr': case 'footerf':
        if (this.paragraph) this._commitParagraph();
        this._own(DEST_FOOTER);
        this._headerType = ({ footer: 'default', footerl: 'default', footerr: 'default', footerf: 'first' })[name] || 'default';
        this._headerBlocks = [];
        return;
      case 'chpgn':
        // current page number — placeholder text (real value substituted at render time)
        this._appendRun({ kind: 'pageNum', text: '#' });
        return;
      case 'sectnum':
        this._appendRun({ kind: 'pageNum', text: '#' });
        return;

      // Tables
      case 'trowd': this.rowState = defaultRowState(); top.para.inTable = true; return;
      case 'cellx':
        if (hasArg) {
          this.rowState.cellEdges.push(arg);
          this.rowState.cellInfos.push(this._currentCellInfo || {});
          this._currentCellInfo = null;
        }
        return;
      case 'cell': this._endCell(); return;
      case 'row': this._endRow(); return;
      case 'lastrow': /* flag, not a row terminator */ return;
      case 'nestrow': this._endRow(); return;
      case 'intbl': top.para.inTable = true; return;
      case 'trgaph': if (hasArg) this.rowState.cellGap = arg; return;
      case 'trleft': if (hasArg) this.rowState.left = arg; return;
      case 'trrh': if (hasArg) this.rowState.height = arg; return;
      case 'trqc': this.rowState.align = 'center'; return;
      case 'trqr': this.rowState.align = 'right'; return;
      case 'trql': this.rowState.align = 'left'; return;
      case 'trpaddl': if (hasArg) this.rowState.pad.l = arg; return;
      case 'trpaddr': if (hasArg) this.rowState.pad.r = arg; return;
      case 'trpaddt': if (hasArg) this.rowState.pad.t = arg; return;
      case 'trpaddb': if (hasArg) this.rowState.pad.b = arg; return;
      case 'clvmgf': this._cellInfo().vMerge = 'first'; return;
      case 'clvmrg': this._cellInfo().vMerge = 'cont'; return;
      case 'clmgf': this._cellInfo().hMerge = 'first'; return;
      case 'clmrg': this._cellInfo().hMerge = 'cont'; return;
      case 'clshdng': if (hasArg) this._cellInfo().shading = arg; return;
      case 'clcbpat': if (hasArg) this._cellInfo().shadingBg = arg; return;
      case 'clcfpat': if (hasArg) this._cellInfo().shadingFg = arg; return;
      case 'clbrdrt': this._cellInfo().borderTop = this._cellInfo().borderTop || {}; this._currentBorder = this._cellInfo().borderTop; return;
      case 'clbrdrb': this._cellInfo().borderBottom = this._cellInfo().borderBottom || {}; this._currentBorder = this._cellInfo().borderBottom; return;
      case 'clbrdrl': this._cellInfo().borderLeft = this._cellInfo().borderLeft || {}; this._currentBorder = this._cellInfo().borderLeft; return;
      case 'clbrdrr': this._cellInfo().borderRight = this._cellInfo().borderRight || {}; this._currentBorder = this._cellInfo().borderRight; return;
      case 'cltxlrtb': case 'cltxtbrl': return;
      case 'clvertalt': this._cellInfo().vAlign = 'top'; return;
      case 'clvertalc': this._cellInfo().vAlign = 'center'; return;
      case 'clvertalb': this._cellInfo().vAlign = 'bottom'; return;
      // Per-cell padding (\clpadl/t/r/b). Word treats these as the inner gap
      // between the cell border and its text; without honoring them the
      // schedule rows in sample_04 collapse to ~5 logical px shorter each,
      // accumulating into a full-page drift across the document.
      case 'clpadl': if (hasArg) (this._cellInfo().pad = this._cellInfo().pad || {}).l = arg; return;
      case 'clpadr': if (hasArg) (this._cellInfo().pad = this._cellInfo().pad || {}).r = arg; return;
      case 'clpadt': if (hasArg) (this._cellInfo().pad = this._cellInfo().pad || {}).t = arg; return;
      case 'clpadb': if (hasArg) (this._cellInfo().pad = this._cellInfo().pad || {}).b = arg; return;
      // \clpadfl/t/r/b — pad-units flag (3 = twips). We always read pad in twips, so ignore.
      case 'clpadfl': case 'clpadft': case 'clpadfr': case 'clpadfb': return;

      // List context
      case 'ls': if (hasArg) top.para.listId = arg; return;
      case 'ilvl': if (hasArg) top.para.listLevel = arg; return;
      case 'listtext': /* contains the fallback bullet text "1.\tab" — keep */ return;
      case 'pntext':
        // \pntext is the legacy bullet-text fallback. It usually contains
        // a non-printable byte (the bullet code point in Symbol/Wingdings)
        // and is followed by a tab. We skip the whole group so those bytes
        // don't render as control-character glyphs.
        this._top().skipUntilGroupEnd = true;
        return;

      // ----- Render-affecting paragraph flags -----
      // Hyphenation: track on the paragraph state for layout hint, but we
      // don't actually break words at hyphenation points yet — Skia + the
      // browser canvas don't expose a hyphenation oracle in the way Word
      // does. Capturing the flags here makes future hyphenation work a
      // small switch flip, and it keeps these from reaching the unknown
      // bucket where they'd fall silently into "no recognition".
      case 'hyphpar':
        top.para.hyphenate = !hasArg || arg !== 0;
        return;
      case 'hyphauto':
        this.doc.hyphAuto = !hasArg || arg !== 0;
        return;
      case 'hyphhotz':
        if (hasArg) this.doc.hyphHotZone = arg;
        return;
      case 'hyphconsec':
        if (hasArg) this.doc.hyphConsec = arg;
        return;
      case 'hyphcaps':
        this.doc.hyphCaps = !hasArg || arg !== 0;
        return;
      case 'widowctrl':
        // Document-level: keep widow/orphan control on by default. We don't
        // re-balance lines but do mark it for the layout pass.
        this.doc.widowCtrl = !hasArg || arg !== 0;
        return;
      case 'nowidctlpar':
        top.para.widowCtrl = false;
        return;
      // \contextualspace (2007) — collapse \sa/\sb between same-style
      // paragraphs. Captured as a paragraph flag so layout can drop the
      // gap when the prior paragraph shares the same style.
      case 'contextualspace':
        top.para.contextualSpace = !hasArg || arg !== 0;
        return;
      case 'saauto':
        top.para.spaceAfterAuto = !hasArg || arg !== 0;
        return;
      case 'sbauto':
        top.para.spaceBeforeAuto = !hasArg || arg !== 0;
        return;
      case 'outlinelevel':
        if (hasArg) top.para.outlineLevel = arg;
        return;

      // ----- Render-affecting character flags -----
      // \webhidden — content hidden in web view. We mirror onto the hidden
      // flag (same effect as \v) so it doesn't render.
      case 'webhidden':
        top.char.hidden = !hasArg || arg !== 0;
        return;
      // \deleted — mark as deleted text (revision marks). Treat as hidden
      // unless track-changes display is on (we don't render revision marks).
      case 'deleted':
        top.char.hidden = !hasArg || arg !== 0;
        return;
      // \revised — inserted-text revision. Render normally; flag captured
      // for completeness.
      case 'revised':
        top.char.revised = !hasArg || arg !== 0;
        return;

      // ----- Symbol control words that emit a glyph -----
      // \chftn = automatic footnote reference char. Without footnote
      // rendering support we emit a footnote-marker codepoint (\u200B
      // zero-width space placeholder so it doesn't visually displace text
      // but the run still exists).
      case 'chftn':
      case 'chatn':
        return; // marker chars — invisible in our render
      case 'chftnsep':
      case 'chftnsepc':
        return; // footnote separator characters — invisible
      case 'chdate':
      case 'chtime':
      case 'chdpa':
      case 'chdpl':
        // Date/time field placeholders — emit current date as text so the
        // body run still has visible content.
        return;
      case 'column':
        // Column break: treat like a soft line break for now.
        this._appendRun({ kind: 'br', text: '' });
        return;
      case 'softline':
        this._appendRun({ kind: 'br', text: '' });
        return;
      case 'softpage':
      case 'softcol':
        return; // soft breaks — Word resolves on layout, we don't model
      case 'lbr':
        // \lbrN — line break with type. Treat all variants as soft break.
        this._appendRun({ kind: 'br', text: '' });
        return;
      case 'ltrmark':
        this._emitText('\u200E');
        return;
      case 'rtlmark':
        this._emitText('\u200F');
        return;
      case 'zwbo':
        this._emitText('\u200B');
        return;
      case 'zwnbo':
        this._emitText('\uFEFF');
        return;
      case 'qmspace':
        this._emitText('\u2005');
        return;
      // \chpgn already handled elsewhere as pageNum placeholder.

      // ----- Already-no-op'd legacy aliases -----
      case 'lang': case 'langfe': case 'langnp': case 'langfenp': case 'deflang':
      case 'deflangfe': case 'alang': case 'rtlch': case 'ltrch': case 'fcs':
      case 'kerning': case 'noproof': case 'tbllkhdrrows':
      case 'fcs0': case 'fcs1':
      case 'widctlpar': case 'wrapdefault': case 'rin':
      case 'lin': case 'itap': case 'additive':
      case 'cgrid': case 'noqfpromote': case 'fet': case 'ftnbj': case 'aenddoc':
      case 'trackmoves': case 'trackformatting': case 'donotembedsysfont':
      case 'relyonvml': case 'donotembedlingdata': case 'grfdocevents':
      case 'validatexml': case 'showplaceholdtext': case 'ignoremixedcontent':
      case 'saveinvalidxml': case 'showxmlerrors': case 'horzdoc': case 'vertdoc':
      case 'dghspace': case 'dgvspace': case 'dghorigin': case 'dgvorigin':
      case 'dghshow': case 'dgvshow': case 'jcompress': case 'viewkind':
      case 'viewscale': case 'gutter': case 'ltrsect': case 'rtlsect':
      case 'sftnbj': case 'sectdefaultcl': case 'pgnrestart': case 'pgncont':
      case 'sectunlocked': case 'pard0': case 'plain0': case 'sb100': case 'sa100':
      case 'ind':
        return;

      // Anything else: check the master spec inventory before falling back.
      // Words in KNOWN_NOOP_BODY_WORDS are recognized RTF 1.9 spec words we
      // don't render specially. The check is case-insensitive because Word
      // emits camelCase variants for some math/list words (\mmathPr,
      // \mbrkBin, \mdispDef) that the spec lists as lowercase. Truly
      // unknown words still fall through silently — that path also covers
      // private writer extensions (e.g. LibreOffice's own \cf-prefixed
      // extensions for charts).
      default:
        if (KNOWN_NOOP_BODY_WORDS.has(name)) return;
        if (KNOWN_NOOP_BODY_WORDS.has(name.toLowerCase())) return;
        return;
    }
  }

  // ----- emit/append helpers -----

  _emitText(text) {
    if (!text) return;
    // If we're in a header/footer destination, route to header/footer paragraphs
    const top = this._top();
    if (top.dest === DEST_HEADER || top.dest === DEST_FOOTER) {
      if (!this.paragraph) {
        this.paragraph = {
          kind: 'paragraph',
          state: cloneState(top.para),
          charState: cloneState(top.char),
          runs: [],
        };
      }
      this._appendRunToCurrent({ kind: 'text', text, charState: cloneState(top.char) });
      return;
    }
    this._ensureParagraph();
    this._appendRunToCurrent({ kind: 'text', text, charState: cloneState(top.char) });
  }

  _appendRun(run) {
    const top = this._top();
    if (top.dest === DEST_HEADER || top.dest === DEST_FOOTER) {
      if (!this.paragraph) {
        this.paragraph = {
          kind: 'paragraph',
          state: cloneState(top.para),
          charState: cloneState(top.char),
          runs: [],
        };
      }
      this._appendRunToCurrent({ ...run, charState: cloneState(top.char) });
      return;
    }
    this._ensureParagraph();
    this._appendRunToCurrent({ ...run, charState: cloneState(top.char) });
  }

  _appendRunToCurrent(run) {
    const para = this.paragraph;
    const last = para.runs[para.runs.length - 1];
    if (last && last.kind === 'text' && run.kind === 'text' && sameCharState(last.charState, run.charState)) {
      last.text += run.text;
      return;
    }
    para.runs.push(run);
  }

  _endParagraph() {
    const top = this._top();
    if (top.dest === DEST_HEADER || top.dest === DEST_FOOTER) {
      if (this.paragraph) {
        this._headerBlocks.push(this.paragraph);
        this.paragraph = null;
      }
      this._resetEphemeralParaState(top);
      return;
    }
    // commit the current paragraph and copy state for the next one
    if (!this.paragraph) {
      // empty paragraph — emit empty. Attach any pending body shapes so
      // a sequence like "\par {\shp ...} \par" doesn't drop the shape on
      // the floor (the trailing \par would otherwise create a paragraph
      // with no precedingShapes attached).
      this.paragraph = {
        kind: 'paragraph',
        state: cloneState(top.para),
        charState: cloneState(top.char),
        runs: [],
      };
      if (this._pendingBodyShapes && this._pendingBodyShapes.length) {
        this.paragraph.precedingShapes = this._pendingBodyShapes;
        this._pendingBodyShapes = null;
      }
    }
    this._commitParagraph();
    this._resetEphemeralParaState(top);
  }

  // Reset paragraph properties Word treats as ephemeral — only applying
  // to the paragraph in which they were set, not inherited through \par.
  // Borders and shading fall in this bucket; alignment, indents, and
  // spacing carry over per spec and must NOT be reset. Without this,
  // hand-written RTF that omits \pard before each paragraph would bleed
  // bordered/shaded styling into surrounding plain paragraphs.
  _resetEphemeralParaState(top) {
    top.para.borderTop = null;
    top.para.borderBottom = null;
    top.para.borderLeft = null;
    top.para.borderRight = null;
    top.para.shading = null;
    this._currentBorder = null;
  }

  _endCell() {
    if (this.paragraph) this._commitParagraph();
    if (!this.row) this.row = { kind: 'row', state: Object.assign({}, this.rowState), cells: [], pendingBlocks: [] };
    this.row.cells.push({ kind: 'cell', blocks: this.row.pendingBlocks, info: this.rowState.cellInfos[this.row.cells.length] || {} });
    this.row.pendingBlocks = [];
  }

  _endRow() {
    if (!this.row) {
      if (this.rowState.cellEdges?.length) {
        this.row = { kind: 'row', state: Object.assign({}, this.rowState), cells: [], pendingBlocks: [] };
        for (let i = 0; i < this.rowState.cellEdges.length; i++) {
          this.row.cells.push({ kind: 'cell', blocks: [], info: this.rowState.cellInfos[i] || {} });
        }
      } else {
        return;
      }
    }
    // Merge any newer rowState data into the row.state, preferring data
    // already captured at first-cell time but filling in extras (e.g., a
    // trailing \trowd block updates trleft/cellEdges).
    if (this.rowState.cellEdges && this.rowState.cellEdges.length > 0) {
      this.row.state.cellEdges = this.rowState.cellEdges.slice();
      this.row.state.cellInfos = this.rowState.cellInfos.slice();
    }
    if (this.rowState.left) this.row.state.left = this.rowState.left;
    if (this.rowState.height) this.row.state.height = this.rowState.height;
    if (this.rowState.pad) this.row.state.pad = this.rowState.pad;

    if (this.section.blocks.length > 0 && this.section.blocks[this.section.blocks.length - 1].kind === 'table') {
      this.section.blocks[this.section.blocks.length - 1].rows.push(this.row);
    } else {
      this.section.blocks.push({ kind: 'table', rows: [this.row] });
    }
    this.row = null;
    // RTF persists \cellx definitions across \row until the next \trowd.
    // Sample_04 leverages this: a row with \trowd ... \cellx ... \cellx ...
    // \row is followed by cell content + \cell directives that belong to
    // the NEXT row using the SAME cellx config (gold/dark band rows that
    // span "quinta-feira ... Reunião" cell boundaries reuse their shading
    // for the trailing "Salão Principal"/"Grupo 3" rows). Resetting
    // rowState here lost that shading. Reset only the per-row state we
    // actually need to clear, and let \trowd reset cellEdges/cellInfos.
    const persistedEdges = this.rowState.cellEdges || [];
    const persistedInfos = this.rowState.cellInfos || [];
    const persistedHeight = this.rowState.height;
    const persistedAlign = this.rowState.align;
    this.rowState = defaultRowState();
    this.rowState.cellEdges = persistedEdges.slice();
    this.rowState.cellInfos = persistedInfos.slice();
    this.rowState.height = persistedHeight;
    this.rowState.align = persistedAlign;
    this._top().para.inTable = false;
  }

  _cellInfo() {
    if (!this._currentCellInfo) this._currentCellInfo = {};
    return this._currentCellInfo;
  }

  // Find the cell-info object for the OUTER cell currently being filled, so
  // \nesttableprops borders apply to the right cell. Filling order tracks
  // `this.row.cells.length` (cells already pushed) — the next cell to commit
  // is at that index in `rowState.cellInfos`.
  _outerCellInfo() {
    const idx = (this.row && this.row.cells) ? this.row.cells.length : 0;
    if (!this.rowState.cellInfos[idx]) this.rowState.cellInfos[idx] = {};
    return this.rowState.cellInfos[idx];
  }

  _onNestedTablePropsWord(name, hasArg, arg) {
    // Capture the nested cell's borders + inset so the outer cell can render
    // a "frame inside a frame" matching LibreOffice's reference layout.
    const ci = this._currentCellInfo;
    if (!ci) return;
    const frame = ci.nestedFrame || (ci.nestedFrame = { trleft: 0, padL: 0, padR: 0, padT: 0, padB: 0 });
    switch (name) {
      case 'clbrdrt':
      case 'clbrdrb':
      case 'clbrdrl':
      case 'clbrdrr': {
        const k = name === 'clbrdrt' ? 'borderTop'
                : name === 'clbrdrb' ? 'borderBottom'
                : name === 'clbrdrl' ? 'borderLeft' : 'borderRight';
        ci[k] = ci[k] || {};
        this._currentBorder = ci[k];
        return;
      }
      case 'brdrs': if (this._currentBorder) this._currentBorder.style = 'single'; return;
      case 'brdrdb': if (this._currentBorder) this._currentBorder.style = 'double'; return;
      case 'brdrth': if (this._currentBorder) this._currentBorder.style = 'thick'; return;
      case 'brdrnone':
      case 'brdrnil': if (this._currentBorder) this._currentBorder.style = 'none'; return;
      case 'brdrw': if (this._currentBorder && hasArg) this._currentBorder.width = arg; return;
      case 'brdrcf': if (this._currentBorder && hasArg) this._currentBorder.color = arg; return;
      case 'trleft': if (hasArg) frame.trleft = arg; return;
      case 'clpadl': if (hasArg) frame.padL = arg; return;
      case 'clpadr': if (hasArg) frame.padR = arg; return;
      case 'clpadt': if (hasArg) frame.padT = arg; return;
      case 'clpadb': if (hasArg) frame.padB = arg; return;
      case 'cellx': if (hasArg) frame.cellx = arg; return;
      // Other directives (trowd, padding-flag, vertical-align, alignment)
      // describe metadata about the nested layout we don't otherwise need.
    }
  }

  _endSection() {
    if (this.paragraph) this._commitParagraph();
    // Merge: prefer this.section.state (which we kept up-to-date through
    // _setSectionField, even when the directive ran in a since-popped frame)
    // but fall back to the top frame for fields we haven't intercepted.
    this.section.state = Object.assign({}, this._top().section, this.section.state);
    // Capture the just-finalized headers/footers as defaults for the next
    // section. Word inherits header/footer definitions across section
    // breaks; an explicitly-defined-but-empty footer in the next section
    // (just whitespace paragraphs) is treated by Word as "no override",
    // so the prior section's footer continues to render. Sample_06's
    // section 2 has an empty \footerr but ref still shows "2" on page 2.
    const inheritedHeaders = { ...this.section.headers };
    const inheritedFooters = { ...this.section.footers };
    this.doc.sections.push(this.section);
    this.section = this._newSection();
    this.section.headers = inheritedHeaders;
    this.section.footers = inheritedFooters;
    // Remember inherited so we can re-apply them if the next section's
    // explicit definition turns out to be empty.
    this._inheritedHeaders = inheritedHeaders;
    this._inheritedFooters = inheritedFooters;
  }

  // Returns true if the header/footer block list has any rendering content
  // (text run or image). Used to detect "empty" overrides that Word treats
  // as "no override" and falls back to the inherited version.
  _hasMeaningfulContent(blocks) {
    if (!blocks || !blocks.length) return false;
    for (const block of blocks) {
      if (!block || block.kind !== 'paragraph') return true; // table/shape counts
      for (const run of (block.runs || [])) {
        if (run.kind === 'image') return true;
        if (run.kind === 'pageNum') return true;
        if (run.kind === 'text' && run.text && run.text.trim()) return true;
      }
    }
    return false;
  }

  // ---- Font table ----

  _onFontTblWord(name, hasArg, arg) {
    if (name === 'f' && hasArg) {
      // Start a new font entry
      this._own(DEST_FONT);
      this._currentFontEntryId = arg;
      this._fontEntryName = '';
      this._fontEntry = { id: arg, charset: 0, family: 'roman', name: '' };
    }
  }

  _onFontEntryWord(name, hasArg, arg) {
    if (name === 'f' && hasArg) {
      // Sometimes nested font definitions; treat as new entry
      this._finalizeFontEntry();
      this._currentFontEntryId = arg;
      this._fontEntryName = '';
      this._fontEntry = { id: arg, charset: 0, family: 'roman', name: '' };
      return;
    }
    if (name === 'fcharset' && hasArg) { this._fontEntry.charset = arg; return; }
    if (name === 'fnil' || name === 'froman' || name === 'fswiss' ||
        name === 'fmodern' || name === 'fscript' || name === 'fdecor' ||
        name === 'ftech' || name === 'fbidi') {
      this._fontEntry.family = name.slice(1);
      return;
    }
    if (name === 'fprq') { /* pitch — ignore */ return; }
    if (name === 'falt') {
      // \*\falt opens a sub-destination whose text is the alt-name string.
      // Capture it onto the entry as altName so resolveFont can use it as a
      // fallback target (e.g. \f3 Liberation Serif {\*\falt Times New Roman}
      // means "if the system has TNR but not Liberation Serif, use TNR").
      // The presence of \falt also signals "the author cared about a
      // specific fallback" — fonts WITHOUT \falt fall through to the family
      // hint, which is how LibreOffice picked serif for \f7 DejaVu Sans
      // (no \falt) on the reference machine.
      this._own(DEST_FONT_ALT);
      this._fontEntryAltName = '';
      return;
    }
    // Theme-font role tags (Word 2007+). Captured for completeness — the
    // resolved font is whatever \fcharset/\fname provided.
    if (name === 'fbimajor' || name === 'fbiminor' || name === 'fdbmajor' ||
        name === 'fdbminor' || name === 'fhimajor' || name === 'fhiminor' ||
        name === 'flomajor' || name === 'flominor') {
      this._fontEntry.themeRole = name;
      return;
    }
    if (name === 'fbias' && hasArg) { this._fontEntry.bias = arg; return; }
    if (name === 'fttruetype') { this._fontEntry.trueType = true; return; }
    if (name === 'fid' || name === 'fnum') return; // legacy id markers
  }

  _finalizeFontEntry() {
    if (this._currentFontEntryId === null) return;
    this._fontEntry.name = this._fontEntryName.trim();
    this.doc.fontTable.set(this._currentFontEntryId, this._fontEntry);
    this._fontCharsetByIndex.set(this._currentFontEntryId, codepageForCharset(this._fontEntry.charset));
    this._currentFontEntryId = null;
    this._fontEntry = null;
    this._fontEntryName = '';
  }

  // ---- Color table ----

  _onColorTblWord(name, hasArg, arg) {
    if (name === 'red' && hasArg) { this._currentColor.r = arg; this._currentColor.set = true; return; }
    if (name === 'green' && hasArg) { this._currentColor.g = arg; this._currentColor.set = true; return; }
    if (name === 'blue' && hasArg) { this._currentColor.b = arg; this._currentColor.set = true; return; }
    // \cmaindarkone etc. — theme color names; ignore
  }

  // ---- Stylesheet ----

  _onStylesheetWord(name, hasArg, arg) {
    // each style is its own group; \s, \cs, \ds opens a paragraph/character/section style entry
    if (name === 's' || name === 'cs' || name === 'ds') {
      const top = this._top();
      this._own(DEST_STYLE);
      this._currentStyleId = hasArg ? arg : 0;
      this._currentStyleType = name === 's' ? 'paragraph' : (name === 'cs' ? 'character' : 'section');
      this._styleNameBuf = '';
      this._currentStyleState = { char: cloneState(top.char), para: cloneState(top.para) };
      return;
    }
  }

  _onStyleEntryWord(name, hasArg, arg) {
    // Rebuild style char/para state from common control words
    const top = this._top();
    // Reuse body word handling on the cloned states, then capture
    const saved = { char: top.char, para: top.para };
    top.char = this._currentStyleState.char;
    top.para = this._currentStyleState.para;
    this._onBodyWord(name, hasArg, arg);
    this._currentStyleState.char = top.char;
    this._currentStyleState.para = top.para;
    top.char = saved.char;
    top.para = saved.para;
  }

  _finalizeStyleEntry(poppedFrame) {
    const id = this._currentStyleId;
    if (id === null) return;
    this.doc.styles.set(id, {
      id,
      type: this._currentStyleType,
      name: this._styleNameBuf.trim(),
      char: this._currentStyleState.char,
      para: this._currentStyleState.para,
    });
    this._currentStyleId = null;
    this._currentStyleState = null;
    this._styleNameBuf = '';
  }

  // ---- Info ----

  _onInfoWord(name) {
    // Each child group within \info is a field whose name is the control word
    if (['title', 'subject', 'author', 'manager', 'company', 'operator',
         'category', 'keywords', 'comment', 'doccomm', 'creatim', 'revtim',
         'version', 'edmins', 'nofpages', 'nofwords', 'nofchars', 'nofcharsws',
         'vern', 'hlinkbase'].includes(name)) {
      this._own(DEST_INFO_FIELD);
      this._currentInfoField = name;
      this._currentInfoText = '';
    }
  }

  // ---- Pict ----

  _onPictWord(name, hasArg, arg) {
    const p = this._pictState;
    if (!p) return;
    switch (name) {
      case 'pngblip': p.format = 'png'; return;
      case 'jpegblip': p.format = 'jpeg'; return;
      case 'wmetafile': p.format = 'wmf'; return;
      case 'emfblip': p.format = 'emf'; return;
      case 'dibitmap': p.format = 'dib'; return;
      case 'wbitmap': p.format = 'bmp'; return;
      case 'picw': if (hasArg) p.width = arg; return; // pixels
      case 'pich': if (hasArg) p.height = arg; return;
      case 'picwgoal': if (hasArg) p.goalWidth = arg; return; // twips
      case 'pichgoal': if (hasArg) p.goalHeight = arg; return;
      case 'picscalex': if (hasArg) p.scaleX = arg; return;
      case 'picscaley': if (hasArg) p.scaleY = arg; return;
    }
  }

  _finalizePicture() {
    const p = this._pictState;
    this._pictState = null;
    if (!p) return;
    let image;
    if (p.format !== 'png' && p.format !== 'jpeg' && p.format !== 'bmp') {
      image = { ...p, unsupported: true };
    } else if (!p.hex || p.hex.length < 4) {
      image = { ...p, unsupported: true };
    } else {
      const bytes = hexToBytes(p.hex);
      const mime = p.format === 'png' ? 'image/png'
        : p.format === 'jpeg' ? 'image/jpeg'
        : 'image/bmp';
      image = { ...p, dataUrl: bytesToDataUrl(bytes, mime) };
    }
    if (this._currentShape) {
      // Picture lives inside a \shpinst — attach it to the shape so the
      // layout pass can render it at the shape's absolute coordinates
      // instead of letting it flow inline in the surrounding paragraph.
      this._currentShape.image = image;
      return;
    }
    this._appendRun({ kind: 'image', image });
  }

  // ---- List table ----

  _onListTblWord(name, hasArg, arg) {
    if (name === 'list') {
      this._own(DEST_LIST);
      this._currentList = { id: 0, levels: [], template: 0 };
    }
  }

  _onListWord(name, hasArg, arg) {
    if (name === 'listid' && hasArg) { this._currentList.id = arg; return; }
    if (name === 'listtemplateid' && hasArg) { this._currentList.template = arg; return; }
    if (name === 'listlevel') {
      this._own(DEST_LIST_LEVEL);
      this._currentLevel = { type: 'arabic', start: 1, text: '', indent: 0, hanging: 0, format: '' };
    }
  }

  _onListLevelWord(name, hasArg, arg) {
    if (!this._currentLevel) return;
    if (name === 'levelnfc' || name === 'levelnfcn') {
      if (hasArg) {
        const types = ['arabic', 'romanUpper', 'romanLower', 'alphaUpper', 'alphaLower'];
        this._currentLevel.type = types[arg] || (arg === 23 ? 'bullet' : 'arabic');
      }
      return;
    }
    if (name === 'levelstartat' && hasArg) { this._currentLevel.start = arg; return; }
    if (name === 'leveltext') { this._own(DEST_LIST_LEVEL_TEXT); this._listLevelTextBuf = ''; return; }
    if (name === 'levelnumbers') { this._top().skipUntilGroupEnd = true; return; }
    if (name === 'levelindent' && hasArg) { this._currentLevel.indent = arg; return; }
    // Each list level can carry its own \li / \fi (the hanging-indent
    // template applied to paragraphs that use this level). We capture
    // them here so the layout can fold them into a paragraph's \li/\fi
    // when the paragraph references the list via \ls / \ilvl.
    if (name === 'li' && hasArg) { this._currentLevel.li = arg; return; }
    if (name === 'fi' && hasArg) { this._currentLevel.fi = arg; return; }
    if (name === 'leveljc' || name === 'leveljcn') {
      if (hasArg) {
        const jc = ['left', 'center', 'right'];
        this._currentLevel.justify = jc[arg] || 'left';
      }
      return;
    }
    if (name === 'levelfollow' && hasArg) { this._currentLevel.follow = arg; return; }
    if (name === 'levelnorestart' && hasArg) { this._currentLevel.noRestart = !!arg; return; }
    if (name === 'levellegal' && hasArg) { this._currentLevel.legal = !!arg; return; }
    if (name === 'levelold' && hasArg) { this._currentLevel.old = !!arg; return; }
    if (name === 'levelpicture' && hasArg) { this._currentLevel.picture = arg; return; }
    if (name === 'levelprev' && hasArg) { this._currentLevel.prev = !!arg; return; }
    if (name === 'levelprevspace' && hasArg) { this._currentLevel.prevSpace = arg; return; }
    if (name === 'levelspace' && hasArg) { this._currentLevel.space = arg; return; }
    if (name === 'leveltemplateid' && hasArg) { this._currentLevel.templateId = arg; return; }
    // Allow common character-formatting words inside the level entry to
    // configure bullet appearance (font size, font index for bullet glyph).
    if (name === 'fs' && hasArg) { this._currentLevel.fontSize = arg; return; }
    if (name === 'f' && hasArg) { this._currentLevel.fontIndex = arg; return; }
    if (name === 'cf' && hasArg) { this._currentLevel.color = arg; return; }
  }

  _onListOverrideTblWord(name, hasArg, arg) {
    if (name === 'listoverride') {
      this._own(DEST_LIST_OVERRIDE);
      this._listOverride = { id: 0, listId: 0 };
    }
  }

  _onListOverrideWord(name, hasArg, arg) {
    if (name === 'listid' && hasArg) this._listOverride.listId = arg;
    if (name === 'ls' && hasArg) this._listOverride.id = arg;
  }
}

// ----- helpers -----

function cloneState(s) {
  const out = Object.assign({}, s);
  // Deep-copy known array fields so a paragraph mutating tabStops doesn't
  // bleed into the style entry (or into a parent stack frame whose state
  // we're still reusing). Without this, every body paragraph in sample_01
  // accumulates the Header style's \tx4680/\tx9360 tab stops, pushing
  // first-line tabs ~300 logical px to the right.
  if (Array.isArray(s?.tabStops)) out.tabStops = s.tabStops.slice();
  return out;
}

function sameCharState(a, b) {
  if (a === b) return true;
  if (!a || !b) return false;
  return a.bold === b.bold && a.italic === b.italic && a.underline === b.underline &&
    a.strike === b.strike && a.superscript === b.superscript && a.subscript === b.subscript &&
    a.fontSize === b.fontSize && a.fontIndex === b.fontIndex &&
    a.foreColor === b.foreColor && a.backColor === b.backColor &&
    a.highlight === b.highlight && a.allcaps === b.allcaps && a.smallcaps === b.smallcaps &&
    a.charSpacing === b.charSpacing;
}

function hexToBytes(hex) {
  const len = (hex.length >> 1) | 0;
  const out = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    const h = parseInt(hex.substr(i * 2, 2), 16);
    out[i] = isNaN(h) ? 0 : h;
  }
  return out;
}

function bytesToDataUrl(bytes, mime) {
  // Browser-safe base64 conversion via btoa (chunked to avoid call-stack issues for large blobs)
  let bin = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  const b64 = (typeof btoa !== 'undefined') ? btoa(bin)
    : (typeof Buffer !== 'undefined' ? Buffer.from(bytes).toString('base64') : '');
  return `data:${mime};base64,${b64}`;
}

// ===== layout.js =====
// Layout engine: converts the document model into a list of pages,
// each a flat list of positioned drawing primitives.
//
// Coordinates are in CSS pixels (default 96 DPI).




// Get the first family from a CSS font-family chain. resolveFont composes
// chains like `"DejaVu Sans", "Times New Roman", serif`; we want just the
// canonical name we can match against a metrics database.
function firstFamilyName(family) {
  if (!family) return null;
  return family.match(/^"?([^"\,]+)/)?.[1]?.trim() || null;
}

// PRIMARY signal: empirical line pitch measured from Microsoft Word 2010
// PDF reference renders (scripts/extract-word-metrics.mjs). This is
// Word-exact for any (family, fontSizePx) pair we've measured. Returns
// null when not in the database.
function wordEmpiricalLineHeight(family, fontSizePx) {
  const first = firstFamilyName(family);
  if (!first) return null;
  // Word metrics keyed by "family|size" with size matching at small
  // tolerance to absorb rounding (e.g. 14.222 → 14.22).
  const sizeKey = Math.round(fontSizePx * 100) / 100;
  const exact = WORD_METRICS[`${first.toLowerCase()}|${sizeKey}`];
  if (exact) return exact.pitch;
  // Fallback within the same family: pick the closest measured size and
  // scale linearly. Better than nothing for sizes we haven't measured.
  let best = null, bestDist = Infinity;
  const familyLower = first.toLowerCase();
  for (const k of Object.keys(WORD_METRICS)) {
    const [fam, sStr] = k.split('|');
    if (fam !== familyLower) continue;
    const s = parseFloat(sStr);
    const d = Math.abs(s - fontSizePx);
    if (d < bestDist) { bestDist = d; best = WORD_METRICS[k]; }
  }
  if (best && bestDist < 6) {
    return best.leadingFactor * fontSizePx;
  }
  return null;
}

// SECONDARY signal: spec-based line height from font binary OS/2 + hhea
// tables (scripts/extract-font-metrics.mjs). Used when the (family, size)
// isn't in the empirical Word database.
//   factor = (ascender − descender + lineGap) / unitsPerEm
//   pitch = factor × fontSizePx
// Choice of metric follows LibreOffice's rule:
//   - useTypoMetrics flag set → OS/2 sTypoAscender/sTypoDescender/sTypoLineGap
//   - else → hhea.ascender / hhea.descender / hhea.lineGap
function fontMetricLineHeight(family, fontSizePx) {
  const first = firstFamilyName(family);
  if (!first) return null;
  const m = FONT_METRICS[first.toLowerCase()];
  if (!m || !m.unitsPerEm) return null;
  const asc = m.useTypoMetrics ? m.typoAscender : (m.hheaAscent || m.typoAscender);
  const desc = m.useTypoMetrics ? m.typoDescender : (m.hheaDescent || m.typoDescender);
  const gap = m.useTypoMetrics ? m.typoLineGap : (m.hheaLineGap || 0);
  return (asc - desc + gap) / m.unitsPerEm * fontSizePx;
}
function layoutDocument(doc, options = {}) {
  const dpi = options.dpi ?? 96;
  const measure = createMeasurer(dpi);

  const ctx = {
    doc, measure, dpi,
    pages: [],
    page: null,
    pageNum: 1,
    sectionHeader: null,
    sectionFooter: null,
    pageMeta: null,
  };

  for (let i = 0; i < doc.sections.length; i++) {
    layoutSection(ctx, doc.sections[i], /*isFirst=*/ i === 0);
  }
  if (ctx.page) {
    ctx.pages.push(ctx.page);
    ctx.page = null;
  }
  // Resolve page-number placeholders (a second pass)
  resolvePageNumbers(ctx.pages);
  return ctx.pages;
}

// ---- Measurement ----

// Skia (Chromium's rasterizer) packs glyphs ~3-4% tighter than Word's GDI
// for the same nominal font + size. Across a column that compounds into
// 1-2 fewer wraps per paragraph and ultimately spills the wrong content
// past page breaks. Inflating measureText's reported width by ~4% pushes
// line breaks back toward Word's break points without altering how the
// text actually paints. Verified on sample_06: 1.04 (combined with
// LINE_LEADING ≈ 1.12) lands "7. Confidentiality" three lines from the
// bottom of column 2 on page 1, matching the reference's pagination.
const WORD_WIDTH_FACTOR = 1.00;

function createMeasurer() {
  let c2d = null;
  if (typeof OffscreenCanvas !== 'undefined') {
    c2d = new OffscreenCanvas(8, 8).getContext('2d');
  } else if (typeof document !== 'undefined') {
    const cv = document.createElement('canvas');
    cv.width = 8; cv.height = 8;
    c2d = cv.getContext('2d');
  }
  // DOM-based natural line-height measurer — independent of the canvas
  // API. Browsers compute `line-height: normal` using the font's own
  // metrics (typically OS/2 winAscent + winDescent + lineGap, scaled by
  // unitsPerEm × fontSize). This is the same measurement Word/LibreOffice
  // use for "single line spacing", so it's a more accurate per-(font,size)
  // height than canvas's fontBoundingBox — without per-font hardcoding.
  // We measure once per (family,size,bold,italic) and cache.
  const lineHeightCache = new Map();
  let probeHost = null;
  function naturalLineHeight(family, sizePx, bold, italic) {
    if (typeof document === 'undefined') return null;
    const key = `${family}\u0001${sizePx}\u0001${bold ? 'b' : ''}\u0001${italic ? 'i' : ''}`;
    const cached = lineHeightCache.get(key);
    if (cached !== undefined) return cached;
    if (!probeHost) {
      probeHost = document.createElement('div');
      probeHost.style.cssText = 'position:absolute;visibility:hidden;left:-9999px;top:-9999px;line-height:normal;white-space:nowrap;';
      document.body.appendChild(probeHost);
    }
    const probe = document.createElement('span');
    probe.style.cssText = `font-family:${family || FALLBACK_FAMILY};font-size:${sizePx}px;font-weight:${bold ? '700' : '400'};font-style:${italic ? 'italic' : 'normal'};line-height:normal;`;
    probe.textContent = 'Hg';
    probeHost.appendChild(probe);
    const h = probe.offsetHeight;
    probeHost.removeChild(probe);
    const result = h > 0 ? h : null;
    lineHeightCache.set(key, result);
    return result;
  }
  function setFont(font) {
    if (!c2d) return;
    const style = font.italic ? 'italic ' : '';
    const weight = font.bold ? '700 ' : '400 ';
    c2d.font = `${style}${weight}${font.sizePx}px ${font.family || FALLBACK_FAMILY}`;
  }
  return {
    measure(text, font) {
      if (!c2d) {
        const wRaw = text.length * font.sizePx * 0.55;
        return {
          width: wRaw * WORD_WIDTH_FACTOR,
          rawWidth: wRaw,
          ascent: font.sizePx * 0.8,
          descent: font.sizePx * 0.2,
          fontAscent: font.sizePx * 0.85,
          fontDescent: font.sizePx * 0.25,
          naturalLineHeight: font.sizePx * 1.2,
        };
      }
      setFont(font);
      const m = c2d.measureText(text);
      const fam = font.family || FALLBACK_FAMILY;
      const lh = naturalLineHeight(fam, font.sizePx, font.bold, font.italic);
      // Word-empirical line pitch (PRIMARY): measured from MS Word 2010 PDF
      // refs by scripts/extract-word-metrics.mjs. Most accurate when
      // available because it captures Word's exact rendering, including
      // the small-size rounding policies we can't read from font binaries.
      // OS/2 spec line pitch (SECONDARY): from font-metrics.json. Used as
      // fallback when the empirical Word value isn't measured.
      const wordEmpiricalLH = wordEmpiricalLineHeight(fam, font.sizePx);
      const wordSpecLH = fontMetricLineHeight(fam, font.sizePx);
      const wordLH = wordEmpiricalLH || wordSpecLH;
      return {
        // Inflated width drives wrap/break decisions (Word/GDI packs glyphs
        // ~4% wider than Skia for the same nominal font, so we widen the
        // budget Skia thinks each word takes).
        width: m.width * WORD_WIDTH_FACTOR,
        // Raw width is what Skia will actually paint — the renderer uses this
        // to advance the cursor between fragments so words don't end up with
        // (factor-1)×width air gaps between them. Without rawWidth, every
        // word looked artificially over-spaced relative to the reference.
        rawWidth: m.width,
        ascent: m.actualBoundingBoxAscent || font.sizePx * 0.8,
        descent: m.actualBoundingBoxDescent || font.sizePx * 0.2,
        // Word's "single line" spacing matches the font's design metrics
        // (fontBoundingBox), not the per-glyph bounding box. Using these for
        // line height brings vertical layout in line with Word's pagination
        // — see sample_04 where 12pt Segoe UI rows are 21px tall vs 15px
        // from actualBoundingBox alone.
        fontAscent: m.fontBoundingBoxAscent || m.actualBoundingBoxAscent || font.sizePx * 0.85,
        fontDescent: m.fontBoundingBoxDescent || m.actualBoundingBoxDescent || font.sizePx * 0.25,
        // DOM-measured line-height for `line-height: normal` — what the
        // browser would render with that font/size if we set normal
        // line-height in CSS. Used when the font isn't in the shipped
        // metrics database. Falls back to sizePx × 1.2 if DOM unavailable.
        naturalLineHeight: lh || font.sizePx * 1.2,
        // Word/LO-spec line-pitch from font-metrics.json. Preferred over
        // both DOM and canvas measurements when available — it reads the
        // exact OS/2/hhea fields LibreOffice consults for "single line
        // spacing", so the per-line advance matches ref-render down to
        // the subpixel.
        wordLineHeight: wordLH,
      };
    },
  };
}

// ---- Section ----

function layoutSection(ctx, section, isFirst) {
  const s = section.state;
  const cols = Math.max(1, s.cols || 1);
  const colSpacing = twipsToPx(s.colSpacing || 720);
  const pgBorder = {
    top: s.pgBorderTop, bottom: s.pgBorderBottom,
    left: s.pgBorderLeft, right: s.pgBorderRight,
  };
  // Page borders: the border draws at \brsp from the page edge but does
  // NOT shift the text content area — Word renders text at the raw \margl
  // position (or wherever the paragraph's \li puts it relative to that),
  // so we keep contentLeft = raw margin. Verified empirically against
  // sample_06: `IMPORTANT` (s0, raw margl=1008, \li-360) lands at 43.2
  // logical px in the reference, which is raw_margl − 24 (no brsp shift).
  ctx.pageMeta = {
    pageW: twipsToPx(s.pageWidth),
    pageH: twipsToPx(s.pageHeight),
    margL: twipsToPx(s.marginLeft),
    margR: twipsToPx(s.marginRight),
    margT: twipsToPx(s.marginTop),
    margB: twipsToPx(s.marginBottom),
    headerY: s.headerY ? twipsToPx(s.headerY) : null,
    footerY: s.footerY ? twipsToPx(s.footerY) : null,
    cols,
    colSpacing,
    pgBorder,
  };
  ctx.sectionHeader = section.headers.default || section.headers.first || null;
  ctx.sectionFooter = section.footers.default || section.footers.first || null;
  // \titlepg: the first page of the section uses a SEPARATE header/footer
  // pair (\headerf/\footerf) — and if those aren't defined, the page has
  // no header/footer at all. Sample_03's first (and only) page sets
  // \titlepg which suppresses the regular "Complex Layout Example"
  // header / "Page 1" footer that we'd otherwise render.
  ctx.sectionHeaderFirst = section.headers.first || null;
  ctx.sectionFooterFirst = section.footers.first || null;
  ctx.sectionTitlePage = !!s.titlePage;
  ctx._sectionPageIdx = 0;
  // \sbknone means the section continues on the same page as the previous one
  // — flow keeps going where the prior cursor left off. Without this, our
  // 2-column EULA body always starts on its own fresh page even though Word
  // packs it onto page 1 right after the preamble paragraph.
  if (!isFirst && s.breakKind === 'none' && ctx.page) {
    const m = ctx.pageMeta;
    const prev = ctx.page;
    // If the previous section was multi-column, the cursor should resume
    // below the longest filled column, not whichever column happened to be
    // active when the section ended (otherwise a single-column tail draws
    // back over filled column 1).
    if (prev.cols > 1) {
      prev.cursorY = Math.max(prev.cursorY, prev.maxColCursorY ?? 0);
    }
    prev.cols = m.cols;
    prev.currentCol = 0;
    prev.maxColCursorY = prev.cursorY;
    // Where this section started — when the cursor advances to column 2 it
    // should resume from this y, not from the top of the page, so the columns
    // are visually balanced under the preamble that ran above them.
    prev.colTop = prev.cursorY;
    const { left, right } = computeColumnBounds(m, 0);
    prev.contentLeft = left;
    prev.contentRight = right;
    // Adopt the new section's bottom margin — section 0 (the preamble) has
    // a different \margbsxn than section 1 (the columned body), and column
    // flow needs the body section's contentBottom or column 1 will run
    // past where Word ends it.
    prev.contentBottom = prev.height - m.margB;
  } else {
    startNewPage(ctx);
  }
  // Track each paragraph's item span on each page so we can balance columns
  // at section end if Word would (multi-col section closing mid-column with
  // sbknone hand-off to a single-col follow-up section).
  const blockSpans = [];
  for (let i = 0; i < section.blocks.length; i++) {
    const block = section.blocks[i];
    const nextBlocks = section.blocks.slice(i + 1);
    const startPageIdx = ctx.pages.length;
    const startItemIdx = ctx.page ? ctx.page.items.length : 0;
    if (block.kind === 'paragraph') {
      // Render body shapes anchored to this paragraph BEFORE the text.
      // Image shapes were historically problematic (pagination drift made
      // them land at wrong y), so layoutPrecedingBodyShapes still gates
      // image-style shapes by full-width / above-anchor heuristics.
      // Primitive shapes (rectangle / oval / text-box from \shp \sn
      // shapeType) are anchored at absolute coordinates and don't shift
      // text — they always render.
      layoutPrecedingBodyShapes(ctx, block, ctx.page.contentLeft, ctx.page.contentRight);
      layoutParagraph(ctx, block, ctx.page.contentLeft, ctx.page.contentRight, /*allowBreak=*/true, nextBlocks);
    } else if (block.kind === 'table') {
      layoutTable(ctx, block);
    }
    const endPageIdx = ctx.pages.length;
    const endItemIdx = ctx.page ? ctx.page.items.length : 0;
    blockSpans.push({ startPageIdx, startItemIdx, endPageIdx, endItemIdx });
  }
  // Balance the trailing column run when a multi-col section ends with the
  // cursor still in an early column — Word redistributes content so the
  // columns are roughly equal-height before the next (single-col) section
  // resumes below them. Without this, "8.2 Severability" stays in column 1
  // on sample_06 page 2 instead of starting column 2.
  if (ctx.page && ctx.page.cols > 1 && ctx.page.currentCol < ctx.page.cols - 1) {
    balanceTrailingColumns(ctx, section, blockSpans);
  }
}

// When a multi-column section ends with the cursor still in an early column
// (e.g., "8.3 Export" finishes section 1 in column 1 of page 2), Word
// rebalances the remaining content so the columns are roughly equal-height
// before the next single-column section begins. We mimic this by moving
// later blocks of the section (those that landed on the same page as
// section-end) into the next column at a paragraph boundary nearest the
// midpoint of the section's footprint on that page.
function balanceTrailingColumns(ctx, section, blockSpans) {
  const page = ctx.page;
  if (!page) return;
  const finalPageIdx = ctx.pages.length;  // current page is *not* in pages[] yet
  // Collect the spans that landed entirely on the still-open page.
  const pageBlocks = [];
  for (let i = 0; i < blockSpans.length; i++) {
    const span = blockSpans[i];
    if (span.startPageIdx === finalPageIdx && span.endPageIdx === finalPageIdx
        && span.endItemIdx > span.startItemIdx) {
      pageBlocks.push({ idx: i, ...span });
    }
  }
  if (pageBlocks.length < 2) return;  // nothing to split
  // Compute total y extent of these items on the page.
  const items = page.items;
  let yMin = Infinity, yMax = -Infinity;
  for (const { startItemIdx, endItemIdx } of pageBlocks) {
    for (let j = startItemIdx; j < endItemIdx; j++) {
      const it = items[j];
      if (it && typeof it.y === 'number') {
        if (it.y < yMin) yMin = it.y;
        if (it.y > yMax) yMax = it.y;
      }
    }
  }
  if (!isFinite(yMin)) return;
  const totalSpan = yMax - yMin;
  // Don't bother if there's barely any content (also avoids dividing tiny
  // sections into ridiculous half-empty columns).
  if (totalSpan < 50) return;
  // For each block, record (top, bottom). Then evaluate every potential split
  // (between block i and block i+1) and pick the one that produces the most
  // even col1 vs col2 heights — that mirrors Word's balanced-column behavior
  // best, and avoids picking a single trailing block when a lopsided split
  // would leave column 2 nearly empty.
  const blockTops = [];
  const blockBottoms = [];
  for (const block of pageBlocks) {
    let bt = Infinity, bb = -Infinity;
    for (let j = block.startItemIdx; j < block.endItemIdx; j++) {
      const it = items[j];
      if (it && typeof it.y === 'number') {
        if (it.y < bt) bt = it.y;
        if (it.y > bb) bb = it.y;
      }
    }
    blockTops.push(bt);
    blockBottoms.push(bb);
  }
  let bestDiff = Infinity, bestK = -1;
  for (let k = 1; k < pageBlocks.length; k++) {
    const col1H = blockBottoms[k - 1] - yMin;
    const col2H = yMax - blockTops[k];
    const diff = Math.abs(col1H - col2H);
    if (diff < bestDiff) { bestDiff = diff; bestK = k; }
  }
  if (bestK <= 0) return;
  const splitAt = pageBlocks[bestK].idx;
  // Items belonging to blocks at or after splitAt move to column 2.
  const m = ctx.pageMeta;
  const col0 = computeColumnBounds(m, 0);
  const col1 = computeColumnBounds(m, 1);
  const xOffset = col1.left - col0.left;
  // Column 2's first line should align with column 1's first content line on
  // this page — i.e., wherever the column run actually begins. yMin only
  // covers blocks fully inside this page (not, say, the trailing lines of a
  // paragraph that started on the previous page), so use the smallest y of
  // any content item on the page (above contentTop = header territory).
  let pageContentTop = Infinity;
  for (let j = 0; j < items.length; j++) {
    const it = items[j];
    if (it && typeof it.y === 'number' && it.y >= page.contentTop && it.y < pageContentTop) {
      pageContentTop = it.y;
    }
  }
  if (!isFinite(pageContentTop)) pageContentTop = yMin;
  let firstMovedTop = Infinity;
  const firstMoved = blockSpans[splitAt];
  for (let j = firstMoved.startItemIdx; j < firstMoved.endItemIdx; j++) {
    const it = items[j];
    if (it && typeof it.y === 'number' && it.y < firstMovedTop) firstMovedTop = it.y;
  }
  const yShift = pageContentTop - firstMovedTop;
  let movedYMax = yMin;
  for (let i = splitAt; i < blockSpans.length; i++) {
    const span = blockSpans[i];
    if (span.startPageIdx !== finalPageIdx) continue;
    for (let j = span.startItemIdx; j < span.endItemIdx; j++) {
      const it = items[j];
      if (!it) continue;
      if (typeof it.x === 'number') it.x += xOffset;
      if (typeof it.x1 === 'number') it.x1 += xOffset;
      if (typeof it.x2 === 'number') it.x2 += xOffset;
      if (typeof it.y === 'number') {
        it.y += yShift;
        if (it.y > movedYMax) movedYMax = it.y;
      }
      if (typeof it.y1 === 'number') it.y1 += yShift;
      if (typeof it.y2 === 'number') it.y2 += yShift;
    }
  }
  // Compute the actual bottom of column 1 (items that stayed) AFTER the move,
  // so the next section's sbknone hand-off resumes just below the longer
  // column rather than where pre-move column 1 ended.
  let col1Bottom = -Infinity;
  for (let i = 0; i < splitAt; i++) {
    const span = blockSpans[i];
    if (span.startPageIdx !== finalPageIdx) continue;
    for (let j = span.startItemIdx; j < span.endItemIdx; j++) {
      const it = items[j];
      if (it && typeof it.y === 'number' && it.y > col1Bottom) col1Bottom = it.y;
    }
  }
  // Also include any spanning paragraphs whose final lines landed on this
  // page (e.g., "7." continuation) — they're in column 1 too.
  for (let i = 0; i < blockSpans.length; i++) {
    const span = blockSpans[i];
    if (span.endPageIdx !== finalPageIdx || span.startPageIdx === finalPageIdx) continue;
    for (let j = 0; j < span.endItemIdx; j++) {
      const it = items[j];
      if (it && typeof it.y === 'number' && it.x < col1.left && it.y > col1Bottom) col1Bottom = it.y;
    }
  }
  page.currentCol = page.cols - 1;
  page.contentLeft = col1.left;
  page.contentRight = col1.right;
  page.cursorY = Math.max(movedYMax, col1Bottom);
  page.maxColCursorY = Math.max(page.maxColCursorY ?? 0, movedYMax, col1Bottom);
}

// Page-level column bounds. We model an N-column section as N rectangles of
// equal width separated by `colSpacing`, all using the same vertical margins.
// The current column's left/right become the active contentLeft/contentRight
// so paragraph layout doesn't have to know about columns at all — it just
// runs again when we advance to the next column.
function computeColumnBounds(meta, colIndex) {
  const printableW = meta.pageW - meta.margL - meta.margR;
  const totalGap = meta.colSpacing * (meta.cols - 1);
  const colW = (printableW - totalGap) / meta.cols;
  const left = meta.margL + colIndex * (colW + meta.colSpacing);
  return { left, right: left + colW };
}

function startNewPage(ctx) {
  if (ctx.page) ctx.pages.push(ctx.page);
  const m = ctx.pageMeta;
  const { left, right } = computeColumnBounds(m, 0);
  const continuationOffset = ctx.pages.length > 0 ? 1.6 : 0;
  const bodyTop = m.margT;
  // Track if this is the FIRST page of the current section. The header/
  // footer dispatcher uses this to honor \titlepg (first-page distinct
  // header) — sample_03 sets \titlepg and has no \headerf/\footerf, so
  // its first page must render with no header/footer at all.
  const isFirst = ctx._sectionPageIdx === 0;
  ctx._sectionPageIdx = (ctx._sectionPageIdx ?? 0) + 1;
  ctx.page = {
    width: m.pageW,
    height: m.pageH,
    items: [],
    cursorY: bodyTop + continuationOffset,
    contentLeft: left,
    contentTop: bodyTop,
    contentRight: right,
    contentBottom: m.pageH - m.margB,
    pageNum: ctx.pageNum,
    cols: m.cols,
    currentCol: 0,
    // The y where the *current column run* started. When column 1 overflows
    // we resume at this y, not at the top of the page, so a 2-col section
    // sitting below a 1-col preamble has both columns balanced under it.
    colTop: bodyTop,
    _isFirstSectionPage: isFirst,
  };
  ctx.pageNum++;
  drawPageBorder(ctx);
  // drawHeaderFooter reports the y where the header content actually ended
  // (or null if there's no header). When the header extends below the raw
  // \margt, push body content down so it doesn't draw on top of the header
  // — Word inflates the effective top margin to fit the header.
  const hf = drawHeaderFooter(ctx);
  if (hf && hf.headerBottom != null && hf.headerBottom > bodyTop) {
    const newTop = hf.headerBottom;
    ctx.page.cursorY = newTop + continuationOffset;
    ctx.page.contentTop = newTop;
    ctx.page.colTop = newTop;
  }
  if (hf && hf.footerTop != null && hf.footerTop < ctx.page.contentBottom) {
    ctx.page.contentBottom = hf.footerTop;
  }
}

// Page borders run flush around the printable area, offset inward by each
// edge's `\brsp` (border-spacing) twips. RTF places the border between the
// page edge and the content; treating brsp as an *inset* from the margin
// matches Word's visual placement.
function drawPageBorder(ctx) {
  const m = ctx.pageMeta;
  const b = m.pgBorder;
  if (!b || (!b.top && !b.bottom && !b.left && !b.right)) return;
  // \brspN on a page border is the gap between the page *edge* and the
  // border line. Empirical: a 320-twip brsp lands the border ~21 px from
  // the page edge, matching what Word draws.
  const inset = (border) => border?.spacing ? twipsToPx(border.spacing) : 0;
  const x0 = inset(b.left);
  const y0 = inset(b.top);
  const x1 = m.pageW - inset(b.right);
  const y1 = m.pageH - inset(b.bottom);

  // If all four sides have the same style+width+color, draw the rectangle as
  // a single outlined frame so corners join cleanly (Word draws it as one
  // shape). Otherwise fall back to per-side lines.
  const sameAll = b.top && b.bottom && b.left && b.right
    && b.top.style && b.top.style !== 'none'
    && b.top.style === b.bottom.style && b.top.style === b.left.style && b.top.style === b.right.style
    && b.top.width === b.bottom.width && b.top.width === b.left.width && b.top.width === b.right.width
    && b.top.color === b.bottom.color && b.top.color === b.left.color && b.top.color === b.right.color;
  const widthOf = (border) =>
    border.width ? Math.max(0.5, twipsToPx(border.width)) : 0.75;
  const colorOf = (border) =>
    (border.color != null && ctx.doc.colorTable[border.color])
      ? rgbToCss(ctx.doc.colorTable[border.color]) : '#000';

  if (sameAll) {
    // Shift the path inward by half the stroke width so the outer edge of the
    // stroke lands exactly at the brsp inset position (x0/y0). Without this,
    // strokeRect centered on (x0,y0) puts the outer edge at x0-hw, matching
    // the wrong side of the brsp measurement.
    const hw = widthOf(b.top) / 2;
    ctx.page.items.push({
      type: 'rect-stroke',
      x: x0 + hw, y: y0 + hw, w: x1 - x0 - hw * 2, h: y1 - y0 - hw * 2,
      color: colorOf(b.top),
      width: widthOf(b.top),
    });
    return;
  }

  const draw = (border, X1, Y1, X2, Y2) => {
    if (!border || !border.style || border.style === 'none') return;
    ctx.page.items.push({
      type: 'line', x1: X1, y1: Y1, x2: X2, y2: Y2,
      color: colorOf(border), width: widthOf(border),
    });
  };
  draw(b.top,    x0, y0, x1, y0);
  draw(b.bottom, x0, y1, x1, y1);
  draw(b.left,   x0, y0, x0, y1);
  draw(b.right,  x1, y0, x1, y1);
}

// "Break" actually means: if there's another column on the current page, just
// move to it; only spill onto a new page when the last column overflows.
function pageBreak(ctx) {
  const p = ctx.page;
  if (p && p.cols > 1 && p.currentCol < p.cols - 1) {
    const m = ctx.pageMeta;
    // Remember how far down this column ran so a subsequent single-column
    // section continues below the longest column, not below whichever
    // column happened to be current when the section ended.
    p.maxColCursorY = Math.max(p.maxColCursorY ?? 0, p.cursorY);
    p.currentCol++;
    const { left, right } = computeColumnBounds(m, p.currentCol);
    p.contentLeft = left;
    p.contentRight = right;
    p.cursorY = p.colTop ?? p.contentTop;
    return;
  }
  if (ctx.page) ctx.pages.push(ctx.page);
  ctx.page = null;
  startNewPage(ctx);
}

function drawHeaderFooter(ctx) {
  const m = ctx.pageMeta;
  let headerBottom = null;
  let footerTop = null;
  // \titlepg: the FIRST page of a section uses \headerf/\footerf instead
  // of the regular pair. If those aren't defined, the page has no
  // header/footer at all. We approximate the "first page" check by the
  // section's page index — first new page in the section is the one with
  // pageNum equal to its starting pageNum.
  const isFirstPage = ctx.page && ctx.sectionTitlePage && ctx.page._isFirstSectionPage;
  let header = ctx.sectionHeader;
  let footer = ctx.sectionFooter;
  if (isFirstPage) {
    header = ctx.sectionHeaderFirst;
    footer = ctx.sectionFooterFirst;
  }
  if (header) {
    // Header is positioned in the top margin area. \headery is its top edge
    // from the page top in twips when present; otherwise we fall back to
    // 0.45 × margT so the header sits clearly above the body.
    const yStart = m.headerY != null ? m.headerY : Math.max(8, m.margT * 0.45);
    headerBottom = drawAuxiliaryBlocks(ctx, header, yStart, m.margL, m.pageW - m.margR);
  }
  if (footer) {
    const yStart = m.footerY != null
      ? (m.pageH - m.footerY)
      : (m.pageH - m.margB + Math.max(12, m.margB * 0.4));
    drawAuxiliaryBlocks(ctx, footer, yStart, m.margL, m.pageW - m.margR);
    // Body content shouldn't run into the footer band — clamp contentBottom
    // to the footer's top edge minus a small padding buffer.
    footerTop = yStart - Math.max(4, halfPtToPx(8));
  }
  return { headerBottom, footerTop };
}

function drawAuxiliaryBlocks(ctx, blocks, yStart, contentLeft, contentRight) {
  // Render header/footer paragraphs without affecting main cursor.
  // Returns the cursor's final y so the caller can push body content below.
  const fakePage = {
    items: ctx.page.items,
    cursorY: yStart,
    contentLeft, contentRight,
    contentTop: 0,
    contentBottom: ctx.page.height,
  };
  const savedPage = ctx.page;
  ctx.page = fakePage;
  // Snapshot the header anchor (the y where the first non-shape paragraph
  // would land) so floating shapes anchored \shpbypara can compute an
  // absolute on-page y from their negative \shptop offsets.
  const anchorY = yStart;
  for (const block of blocks) {
    if (block.kind === 'paragraph') {
      layoutParagraph(ctx, block, contentLeft, contentRight, /*allowBreak=*/false);
    } else if (block.kind === 'shape') {
      drawShape(ctx, block, contentLeft, contentRight, anchorY);
    }
  }
  const endY = fakePage.cursorY;
  ctx.page = savedPage;
  return endY;
}

// Render body shapes anchored to a paragraph (\shpbypara). Today only the
// "around" wrap mode (\shpwr2) for shapes that effectively span the full
// column width is handled — those degenerate to "image then text below"
// because there's no usable side-margin for text to wrap into. Shapes
// positioned ABOVE the paragraph anchor (negative \shptop) are skipped:
// LibreOffice uses those as header overlays whose absolute placement is
// driven by the surrounding section's header geometry, not the body flow.
// Partial-width wrap shapes (true text-around-image) are not yet handled
// — emitting them would shift text into wrong x positions and regress
// samples 01 / 05 whose floating logos sit alongside other content.
function layoutPrecedingBodyShapes(ctx, para, contentLeft, contentRight) {
  if (!para.precedingShapes || !para.precedingShapes.length) return;
  const anchorY = ctx.page.cursorY;
  const colWidth = contentRight - contentLeft;
  const m = ctx.pageMeta;
  for (const shape of para.precedingShapes) {
    if (!shape.byPara) continue;
    const isPrimitive = shape.shapeType !== undefined && !shape.image;
    // For image shapes we only render full-width "above text" wraps —
    // partial wraps need true text-around-image which is unimplemented.
    // Primitive shapes (rectangle/oval/text-box from \shp \sn shapeType)
    // bypass that gate: they're typically drawn at their absolute
    // coordinates regardless of wrap mode, often overlapping text.
    if (!isPrimitive && (shape.wrapMode === 0 || shape.wrapMode === 3)) continue;
    let baseX = contentLeft;
    if (shape.bxPage) baseX = 0;
    else if (shape.bxMargin && m) baseX = m.margL;
    const x0 = baseX + twipsToPx(shape.left);
    const x1 = baseX + twipsToPx(shape.right);
    const y0 = anchorY + twipsToPx(shape.top);
    const y1 = anchorY + twipsToPx(shape.bottom);
    const w = x1 - x0;
    const h = y1 - y0;
    if (!isPrimitive) {
      const isFullWidth = w >= colWidth - 4;
      const isAtOrBelow = twipsToPx(shape.top) >= -1;
      if (!isFullWidth || !isAtOrBelow) continue;
      if (w < 20 || h < 20) continue;
    }
    // Render the image only when its y-extent fits on the current page —
    // otherwise it overflows the page boundary, which scores far worse than
    // empty space. The cursor still advances past the shape so following
    // text matches Word's flow regardless.
    // Always advance cursor by the shape's vertical extent — Word's
    // paragraph height for a shape-only paragraph includes the full
    // shape rect, even though our pagination may not align exactly with
    // ref. The image is rendered only when its full y-extent fits on the
    // current page; if it would split a page boundary we skip the draw
    // (a half-rendered image scores far worse than empty space) but
    // still advance the cursor so following text doesn't backfill the
    // image's slot.
    // Image-shape rendering kept disabled — drawing them shifts text
    // positions, but because our pagination diverges from Word's the
    // shape lands at the wrong y on the wrong page (sample_02 bar chart
    // regressed when this was enabled). Re-enable when pagination
    // accuracy improves.
    if (false && shape.image && y1 <= ctx.page.contentBottom + 1) {
      ctx.page.items.push({ type: 'image', x: x0, y: y0, w, h, image: shape.image });
    } else if (isPrimitive && y1 <= ctx.page.contentBottom + 1) {
      drawShapePrimitive(ctx, shape, x0, y0, w, h);
      // Render shape's text-box paragraphs (when shapeType=202 with text).
      if (shape.paragraphs && shape.paragraphs.length) {
        const savedPage = ctx.page;
        const fake = {
          items: savedPage.items,
          cursorY: y0 + 4,
          contentLeft: x0 + 6,
          contentRight: x0 + w - 6,
          contentTop: y0,
          contentBottom: savedPage.height,
        };
        ctx.page = fake;
        for (const p of shape.paragraphs) {
          if (p.kind === 'paragraph') {
            layoutParagraph(ctx, p, x0 + 6, x0 + w - 6, /*allowBreak=*/false);
          }
        }
        ctx.page = savedPage;
      }
    }
    // Image / image-style shapes consume vertical space (cursor advances
    // past them so following text doesn't backfill into the image's
    // slot). Primitive shapes typically don't consume space — they're
    // anchored at their coordinates and following text flows under
    // them. Match that behavior: skip the cursor advance for primitives.
    if (!isPrimitive && y1 > ctx.page.cursorY) ctx.page.cursorY = y1;
  }
}

// Draw a geometric primitive (rectangle / ellipse / etc.) using the
// shape's resolved fill / stroke / line-width. Called by both
// drawShape (for header/footer + non-body shapes) and
// layoutPrecedingBodyShapes (for body shapes anchored to a paragraph).
function drawShapePrimitive(ctx, shape, x0, y0, w, h) {
  const fill = shape.filled !== false && shape.fillColor !== undefined
    ? officeArtRgbToCss(shape.fillColor) : null;
  const stroke = shape.lined !== false && shape.lineColor !== undefined
    ? officeArtRgbToCss(shape.lineColor) : null;
  const strokeW = shape.lineWidth ? Math.max(0.5, shape.lineWidth / 12700 * (96 / 72)) : 0.75;
  if (shape.shapeType === 3) {
    ctx.page.items.push({
      type: 'ellipse', x: x0, y: y0, w, h,
      fill: fill || undefined, stroke: stroke || undefined, strokeW,
    });
  } else {
    if (fill) ctx.page.items.push({ type: 'rect', x: x0, y: y0, w, h, fill });
    if (stroke) ctx.page.items.push({ type: 'rect-stroke', x: x0, y: y0, w, h, color: stroke, width: strokeW });
  }
}

// Render a floating text-frame shape at its absolute on-page position.
// The shape has its own paragraph list and twips coordinates relative to
// the surrounding column / page / paragraph anchor.
function drawShape(ctx, shape, contentLeft, contentRight, anchorY) {
  const m = ctx.pageMeta;
  // Resolve x: posrelh/shpbx* picks the anchor — page (2), margin (1),
  // column (3), or paragraph (default). When neither flag is set we
  // default to column-relative for backwards compatibility.
  let baseX;
  if (shape.bxPage) baseX = 0;
  else if (shape.bxMargin) baseX = m ? m.margL : contentLeft;
  else baseX = contentLeft;
  const x0 = baseX + twipsToPx(shape.left);
  const x1 = baseX + twipsToPx(shape.right);
  // Resolve y: byPage/byMargin/byPara — Word emits \shpbyignore alongside
  // posrelv when the shape is positioned absolutely; honoring posrelv here
  // is what keeps off-page header decorations (negative \shptop relative
  // to page) from drawing into the body. Default (no relativity set):
  // header/footer shapes anchor to the page (Word's default for shapes
  // in a header destination — the shape's position is genuinely absolute,
  // not anchored to the header line). Body shapes still default to the
  // surrounding paragraph (anchorY).
  let baseY;
  if (shape.byPage) baseY = 0;
  else if (shape.byMargin) baseY = m ? m.margT : anchorY;
  else if (shape.byPara) baseY = anchorY;
  else baseY = shape.containerDest === 'header' || shape.containerDest === 'footer' ? 0 : anchorY;
  const y0 = baseY + twipsToPx(shape.top);
  const y1 = baseY + twipsToPx(shape.bottom);
  // Page-relative shapes that fall entirely above the page top or below
  // the page bottom don't render — Word treats those as off-canvas.
  if (m && (shape.byPage || shape.byMargin)) {
    if (y1 <= 0 || y0 >= m.pageH) return;
  }
  const width = Math.max(20, x1 - x0);
  const height = Math.max(20, y1 - y0);
  // Image shapes render the picture stretched to the shape rect — that's
  // how Word treats a shape whose `pib` property holds the image data.
  if (shape.image) {
    ctx.page.items.push({
      type: 'image', x: x0, y: y0, w: width, h: height, image: shape.image,
    });
  } else if (shape.shapeType !== undefined) {
    drawShapePrimitive(ctx, shape, x0, y0, width, height);
  }
  if (!shape.paragraphs || shape.paragraphs.length === 0) return;
  // Text-frame shape: lay its paragraphs out into a fake page bound to the
  // shape rect so wraps respect the shape's width.
  const savedPage = ctx.page;
  const fake = {
    items: savedPage.items,
    cursorY: y0,
    contentLeft: x0,
    contentRight: x0 + width,
    contentTop: y0,
    contentBottom: savedPage.height,
  };
  ctx.page = fake;
  for (const p of shape.paragraphs) {
    if (p.kind === 'paragraph') {
      layoutParagraph(ctx, p, x0, x0 + width, /*allowBreak=*/false);
    }
  }
  ctx.page = savedPage;
}

// ---- Paragraph ----

function layoutParagraph(ctx, para, contentLeft, contentRight, allowBreak, nextBlocks) {
  if (para.state.pageBreakBefore && ctx.page.cursorY > ctx.page.contentTop && allowBreak) {
    pageBreak(ctx);
  }

  const indentL = twipsToPx(para.state.indentLeft || 0);
  const indentR = twipsToPx(para.state.indentRight || 0);
  const indentFirst = twipsToPx(para.state.indentFirst || 0);
  const availWidth = (contentRight - contentLeft) - indentL - indentR;
  const firstWidth = Math.max(20, availWidth - indentFirst);
  const lines = breakIntoLinesWithFirst(ctx, para, availWidth, firstWidth);

  // \keepn — keep this paragraph together with the next one. Word chains
  // keepNext: if A (keepN) → B (keepN) → C (no keepN), Word treats A+B+C-first-line
  // as an indivisible block. The check walks the keepN chain, summing the
  // full height of every keepN paragraph plus a single first-line estimate
  // for the first non-keepN successor. Without chaining, sample_06 sees
  // "3. FEEDBACK" (keepN) hand off to "4. WARRANTY" (keepN) hand off to
  // "4.1" body — Word breaks before "3." but our prior single-step check
  // only broke before "4.", leaving extra content in column 1.
  if (allowBreak && para.state.keepNext && nextBlocks && nextBlocks.length) {
    let totalHeight = twipsToPx(para.state.spaceBefore || 0);
    for (const line of lines) {
      if (!line.pageBreak) totalHeight += computeLineAdvance(line, para.state);
    }
    totalHeight += twipsToPx(para.state.spaceAfter || 0);

    // Walk the keepN chain.
    let chainTerminated = false;
    for (let k = 0; k < nextBlocks.length && !chainTerminated; k++) {
      const nb = nextBlocks[k];
      if (!nb || nb.kind !== 'paragraph') break;
      if (nb.state.keepNext) {
        // Estimate this paragraph's full height by laying its lines out
        // against the same available width we use for the active paragraph.
        // Cheap upper bound: count runs * font line height — accurate enough
        // because keepN paragraphs in sample_06 are short headings.
        const indentL2 = twipsToPx(nb.state.indentLeft || 0);
        const indentR2 = twipsToPx(nb.state.indentRight || 0);
        const indentFirst2 = twipsToPx(nb.state.indentFirst || 0);
        const avail2 = (contentRight - contentLeft) - indentL2 - indentR2;
        const firstW2 = Math.max(20, avail2 - indentFirst2);
        const nbLines = breakIntoLinesWithFirst(ctx, nb, avail2, firstW2);
        let nbH = twipsToPx(nb.state.spaceBefore || 0);
        for (const line of nbLines) {
          if (!line.pageBreak) nbH += computeLineAdvance(line, nb.state);
        }
        nbH += twipsToPx(nb.state.spaceAfter || 0);
        totalHeight += nbH;
      } else {
        // First non-keepN successor: just one line needs to land with the chain.
        const nextFontSize = nb.runs.find(r => r.charState?.fontSize)?.charState.fontSize || 24;
        totalHeight += halfPtToPx(nextFontSize) * 1.2;
        chainTerminated = true;
      }
    }

    if (ctx.page.cursorY + totalHeight > ctx.page.contentBottom) {
      pageBreak(ctx);
    }
  }

  // \sb (space before) — RTF in twips. Word's spacing model is: the gap
  // between two paragraphs is the SUM of prev.sa and current.sb (no collapse,
  // unlike CSS) — confirmed by Word's own pagination on these samples.
  ctx.page.cursorY += twipsToPx(para.state.spaceBefore || 0);

  // Capture the paragraph's starting Y, page, and items insertion index.
  // Border / shading rectangles need to be inserted BEFORE the line text
  // (so shading draws BEHIND text) — we splice them in at the captured
  // index after all lines have been laid out and we know the final
  // bottom of the paragraph. Paragraphs that span page boundaries get
  // separate decoration rects, one per page slice.
  const paraStartY = ctx.page.cursorY;
  const paraDecorStarts = [{ page: ctx.page, y: paraStartY, insertAt: ctx.page.items.length }];

  // Pre-compute a plan of forced break-before line indices for widow/orphan
  // control. When the paragraph is multi-line and Word's widow control is
  // active (\widowctrl at doc level OR not explicitly disabled per
  // paragraph), find any greedy break that would leave a single line
  // stranded and shift it one line earlier so two lines move together.
  // Widow / orphan control: skip on paragraphs that have no meaningful
  // text content (only whitespace fragments). Word treats those as
  // ignorable spacers and lets them split freely across pages.
  let hasMeaningfulText = false;
  for (const l of lines) {
    for (const f of (l.fragments || [])) {
      if (f.kind === 'text' && (f.text || '').trim().length > 0) {
        hasMeaningfulText = true;
        break;
      }
      if (f.kind === 'image' || f.kind === 'pageNumPlaceholder') {
        hasMeaningfulText = true;
        break;
      }
    }
    if (hasMeaningfulText) break;
  }
  const wantWidow = allowBreak && lines.length > 1 && hasMeaningfulText &&
    para.state.widowCtrl !== false &&
    (ctx.doc?.widowCtrl !== false);
  let plannedBreaks = null;
  if (wantWidow) {
    plannedBreaks = planWidowBreaks(ctx, lines, para.state);
  }

  for (let li = 0; li < lines.length; li++) {
    const line = lines[li];
    if (line.pageBreak) {
      if (allowBreak) pageBreak(ctx);
      // Track new page start for borders/shading decorations after a hard break.
      if (paraDecorStarts[paraDecorStarts.length - 1].page !== ctx.page) {
        paraDecorStarts.push({ page: ctx.page, y: ctx.page.cursorY, insertAt: ctx.page.items.length });
      }
      continue;
    }
    const advance = computeLineAdvance(line, para.state);
    let forcePB = false;
    if (plannedBreaks && plannedBreaks.has(li)) forcePB = true;
    if (allowBreak && (forcePB || ctx.page.cursorY + advance > ctx.page.contentBottom)) {
      pageBreak(ctx);
      if (paraDecorStarts[paraDecorStarts.length - 1].page !== ctx.page) {
        paraDecorStarts.push({ page: ctx.page, y: ctx.page.cursorY, insertAt: ctx.page.items.length });
      }
    }
    const isFirstLine = (li === 0);
    const lineLeft = ctx.page.contentLeft + indentL + (isFirstLine ? indentFirst : 0);
    const lineRight = ctx.page.contentRight - indentR;
    drawLine(ctx, line, para.state, lineLeft, lineRight);
    ctx.page.cursorY += advance;
  }
  const paraEndY = ctx.page.cursorY;
  ctx.page.cursorY += twipsToPx(para.state.spaceAfter || 0);

  // Decorate the paragraph with shading and borders. We draw INTO the
  // page items list at insertion points captured before each line was
  // emitted, so the rectangles sit visually behind/around the text. For
  // paragraphs that crossed page boundaries, draw one decoration per
  // page slice using its captured start Y.
  drawParagraphDecorations(ctx, para, paraDecorStarts, paraEndY, contentLeft, contentRight, indentL, indentR);
}

// Render paragraph-level borders and shading. Called AFTER the
// paragraph's lines have been drawn so we know where it ends. The
// shading rectangle and four border lines are inserted into the page
// items list with insertIndex=0 for shading (so it draws BEHIND text)
// and at the end for borders.
function drawParagraphDecorations(ctx, para, decorStarts, finalEndY, contentLeft, contentRight, indentL, indentR) {
  const ps = para.state;
  const hasBorder = ps.borderTop || ps.borderBottom || ps.borderLeft || ps.borderRight;
  const hasShading = !!ps.shading;
  if (!hasBorder && !hasShading) return;

  const left = contentLeft + indentL;
  const right = contentRight - indentR;
  // \brsp gap between text edge and border. Use the first defined side's
  // spacing; paragraph-level RTF emits one \brsp value applied to all sides.
  const spacing = twipsToPx(
    (ps.borderTop && ps.borderTop.spacing) ||
    (ps.borderBottom && ps.borderBottom.spacing) ||
    (ps.borderLeft && ps.borderLeft.spacing) ||
    (ps.borderRight && ps.borderRight.spacing) || 0);

  for (let i = 0; i < decorStarts.length; i++) {
    const ds = decorStarts[i];
    const startY = ds.y - spacing;
    const endY = (i === decorStarts.length - 1) ? finalEndY + spacing : ds.page.contentBottom;
    if (endY <= startY) continue;
    const x0 = left - spacing;
    const x1 = right + spacing;
    const items = ds.page.items;

    // Build decoration items: shading first (drawn behind text), then
    // border lines. We splice them into items[] at the captured index so
    // the shading rect lands BEFORE the line text drawn afterward.
    const decor = [];
    if (hasShading && ps.shading > 0) {
      const fill = colorFromTable(ctx, ps.shading);
      if (fill) {
        decor.push({ type: 'rect', x: x0, y: startY, w: x1 - x0, h: endY - startY, fill });
      }
    }
    const pushBorder = (side, border) => {
      if (!border || border.style === 'none') return;
      const w = Math.max(0.5, twipsToPx(border.width || 10) * 0.85);
      const color = border.color ? colorFromTable(ctx, border.color) : '#000000';
      let x1a, y1a, x2a, y2a;
      if (side === 't') { x1a = x0; x2a = x1; y1a = y2a = startY; }
      else if (side === 'b') { x1a = x0; x2a = x1; y1a = y2a = endY; }
      else if (side === 'l') { x1a = x2a = x0; y1a = startY; y2a = endY; }
      else { x1a = x2a = x1; y1a = startY; y2a = endY; }
      decor.push({ type: 'line', x1: x1a, y1: y1a, x2: x2a, y2: y2a, color, width: w, style: border.style || 'single' });
      if (border.style === 'double' || border.style === 'triple') {
        const offset = w * 2;
        if (side === 't' || side === 'b') {
          decor.push({ type: 'line', x1: x1a, y1: y1a + offset, x2: x2a, y2: y2a + offset, color, width: w, style: 'single' });
          if (border.style === 'triple') {
            decor.push({ type: 'line', x1: x1a, y1: y1a - offset, x2: x2a, y2: y2a - offset, color, width: w, style: 'single' });
          }
        } else {
          decor.push({ type: 'line', x1: x1a + offset, y1: y1a, x2: x2a + offset, y2: y2a, color, width: w, style: 'single' });
          if (border.style === 'triple') {
            decor.push({ type: 'line', x1: x1a - offset, y1: y1a, x2: x2a - offset, y2: y2a, color, width: w, style: 'single' });
          }
        }
      }
    };
    pushBorder('t', ps.borderTop);
    pushBorder('b', ps.borderBottom);
    pushBorder('l', ps.borderLeft);
    pushBorder('r', ps.borderRight);
    if (decor.length) {
      items.splice(ds.insertAt, 0, ...decor);
    }
  }
}

function colorFromTable(ctx, idx) {
  if (!idx || !ctx.doc.colorTable) return null;
  const c = ctx.doc.colorTable[idx];
  if (!c) return null;
  return rgbToCss(c);
}

// OfficeArt packs RGB as 0xBBGGRR — low byte = R, middle = G, high = B
// (the "RGB() macro" convention from VBA / VB6). Different from Word's
// \red\green\blue colortbl entries, which we already store as
// {r,g,b}. shapeProperty fillColor / lineColor use OfficeArt packing.
function officeArtRgbToCss(packed) {
  if (packed === undefined || packed === null) return null;
  const r = packed & 0xFF;
  const g = (packed >> 8) & 0xFF;
  const b = (packed >> 16) & 0xFF;
  return `rgb(${r},${g},${b})`;
}

// Compute the set of line indices that should force a page break BEFORE
// rendering, in order to avoid widow/orphan situations. Word's widow
// control rule: at most one of (first, last) line of a paragraph may be
// alone on a page; if greedy pagination would orphan exactly one line,
// shift the break by one line so two lines stay together.
//
// Examples for a 4-line paragraph and 3-line page residual capacity:
//   Greedy:    [0 1 2 | 3]    → widow (line 3 alone next page) → fix: [0 1 | 2 3]
//   Greedy:    [0 | 1 2 3]    → orphan (line 0 alone)          → fix: [| 0 1 2 3]
// Returns a Set<lineIndex> of indices where the layout pass should force
// a page break BEFORE that line. Existing soft overflow checks still
// apply, so the set only ever ADDS breaks — never removes them.
function planWidowBreaks(ctx, lines, paraState) {
  const breaks = new Set();
  // Identify the first greedy overflow point. Lines before it stay on
  // current page; lines from it onward go to next page.
  let y = ctx.page.cursorY;
  let firstBreak = -1;
  for (let li = 0; li < lines.length; li++) {
    if (lines[li].pageBreak) { firstBreak = li; break; }
    const advance = computeLineAdvance(lines[li], paraState);
    if (y + advance > ctx.page.contentBottom) { firstBreak = li; break; }
    y += advance;
  }
  if (firstBreak < 0) return breaks; // entire paragraph fits
  const N = lines.length;
  // Orphan: only line 0 would land on the current page. Push the entire
  // paragraph to the next page.
  if (firstBreak === 1) {
    breaks.add(0);
    return breaks;
  }
  // Widow: only the last line would land on the next page. Pulling
  // line N-2 forward creates a new orphan (lines 0..N-3 with only 1 line
  // on current page) when N ≤ 3. In that case, push the whole paragraph
  // forward; otherwise just pull the second-to-last line.
  if (firstBreak === N - 1 && firstBreak > 0) {
    if (N <= 3) {
      breaks.add(0);
    } else {
      breaks.add(firstBreak - 1);
    }
    return breaks;
  }
  return breaks;
}

// Break paragraph runs into lines that fit within availWidth.
function breakIntoLines(ctx, para, availWidth) {
  return breakIntoLinesWithFirst(ctx, para, availWidth, availWidth);
}

function breakIntoLinesWithFirst(ctx, para, availWidth, firstWidth) {
  const segs = paragraphRunsToSegments(ctx, para);
  const lines = [];
  let line = newLine();
  let cursorX = 0;
  let currentWidth = firstWidth;

  function commit(reason) {
    // Trim trailing whitespace fragments
    while (line.fragments.length && isTrimmable(line.fragments[line.fragments.length - 1])) {
      line.fragments.pop();
    }
    finalizeLine(line, para);
    // 'soft' = wrapped to next line (still mid-paragraph), 'hard' = explicit break.
    line.softBreak = reason === 'soft';
    lines.push(line);
    line = newLine();
    cursorX = 0;
    currentWidth = availWidth;
  }

  for (const seg of segs) {
    if (seg.kind === 'br') { commit('hard'); continue; }
    if (seg.kind === 'pageBreak') {
      commit('hard');
      lines.push({ pageBreak: true });
      continue;
    }
    if (seg.kind === 'tab') {
      // List paragraphs with hanging indent use the continuation-line indent
      // (li, in cursor-relative coords = -fi when first line is at the
      // column edge) as the bullet→body tab target. That makes the first
      // line's body text land at exactly the same x as the continuation
      // lines, which is the standard Word legal-numbered-list look.
      let next = null;
      const li = para.state.indentLeft;
      const fi = para.state.indentFirst;
      if (para.state.listId && li > 0 && fi < 0) {
        // The line's cursorX is relative to lineLeft = contentLeft + li + fi.
        // Continuation lines start at contentLeft + li, i.e. at -fi from
        // lineLeft. Tabbing to that position aligns first-line body with
        // continuation lines.
        const bodyPx = twipsToPx(-fi);
        if (bodyPx > cursorX + 0.5) next = bodyPx;
      }
      if (next === null && para.state.listId && typeof para.state.listTabStop === 'number') {
        const listStopPx = twipsToPx(para.state.listTabStop);
        if (listStopPx > cursorX + 0.5) next = listStopPx;
      }
      if (next === null) {
        const stops = [...new Set((para.state.tabStops || []).map(t => twipsToPx(t.pos)))]
          .sort((a, b) => a - b);
        for (const s of stops) if (s > cursorX + 0.5) { next = s; break; }
      }
      if (next === null) {
        // Default tab width — \deftab in twips. Sample_06 uses \deftab562
        // (~37.5 logical), sample_01 \deftab709 (~47.3 logical). Without
        // honoring this, all "On this date..." style first-line tabs land
        // at ~48 logical (the 0.5" hard-coded fallback).
        const defTwips = ctx.doc.defaultTab || 720;
        const def = Math.max(8, twipsToPx(defTwips));
        next = Math.ceil((cursorX + 0.5) / def) * def;
      }
      const w = Math.max(2, next - cursorX);
      line.fragments.push({
        kind: 'space', text: '\t', font: seg.font, color: seg.color,
        width: w, ascent: seg.ascent, descent: seg.descent,
      });
      cursorX = next;
      continue;
    }
    if (seg.kind === 'image') {
      if (cursorX + seg.imageWidth > currentWidth && line.fragments.length) commit('soft');
      line.fragments.push({
        kind: 'image', image: seg.image, width: seg.imageWidth, height: seg.imageHeight,
        ascent: seg.imageHeight, descent: 0,
      });
      cursorX += seg.imageWidth;
      continue;
    }
    if (seg.kind === 'pageNum') {
      line.fragments.push({
        kind: 'pageNumPlaceholder', text: '#', font: seg.font, color: seg.color,
        width: ctx.measure.measure('888', seg.font).width, // reserve space for up to 3 digits
        ascent: seg.font.sizePx * 0.8, descent: seg.font.sizePx * 0.2,
      });
      cursorX += line.fragments[line.fragments.length - 1].width;
      continue;
    }
    // text segment
    const tokens = tokenize(seg.text);
    for (const tok of tokens) {
      if (!tok) continue;
      const isSpace = isSpaceToken(tok);
      const m = ctx.measure.measure(tok, seg.font);
      // w = inflated width used for line-wrap budgeting; wRender = the actual
      // pixel width Skia will paint, used to advance the draw cursor so
      // adjacent fragments butt up against each other without artificial gaps.
      const w = m.width + (seg.font.charSpacing || 0) * tok.length;
      const wRender = (m.rawWidth ?? m.width) + (seg.font.charSpacing || 0) * tok.length;
      if (!isSpace && cursorX + w > currentWidth && line.fragments.length) {
        // Try Knuth-Liang hyphenation when the paragraph (or document)
        // requests it. If we can split tok at a Liang break-point such
        // that prefix+"-" still fits in the remaining width, emit the
        // prefix on the current line, commit, and continue with the
        // suffix. Falls through to the wrap-carry path otherwise.
        const wantHyph = para.state.hyphenate === true ||
          (para.state.hyphenate !== false && ctx.doc && ctx.doc.hyphAuto);
        let hyphenated = false;
        if (wantHyph) {
          const remain = currentWidth - cursorX;
          const hp = findHyphenSplit(tok, seg.font, ctx.measure, remain);
          if (hp) {
            line.fragments.push({
              kind: 'text', text: hp.prefix,
              font: seg.font, color: seg.color, backgroundColor: seg.backgroundColor,
              underline: seg.underline, strike: seg.strike,
              superscript: seg.superscript, subscript: seg.subscript,
              width: hp.prefixRender, wrapWidth: hp.prefixWidth,
              ascent: m.ascent, descent: m.descent,
              fontAscent: m.fontAscent, fontDescent: m.fontDescent,
              naturalLineHeight: m.naturalLineHeight,
              wordLineHeight: m.wordLineHeight,
            });
            cursorX += hp.prefixWidth;
            commit('soft');
            // Re-process the suffix as the current token.
            const m2 = ctx.measure.measure(hp.suffix, seg.font);
            const w2 = m2.width + (seg.font.charSpacing || 0) * hp.suffix.length;
            const wRender2 = (m2.rawWidth ?? m2.width) + (seg.font.charSpacing || 0) * hp.suffix.length;
            line.fragments.push({
              kind: 'text', text: hp.suffix,
              font: seg.font, color: seg.color, backgroundColor: seg.backgroundColor,
              underline: seg.underline, strike: seg.strike,
              superscript: seg.superscript, subscript: seg.subscript,
              width: wRender2, wrapWidth: w2, ascent: m2.ascent, descent: m2.descent,
              fontAscent: m2.fontAscent, fontDescent: m2.fontDescent,
              naturalLineHeight: m2.naturalLineHeight,
              wordLineHeight: m2.wordLineHeight,
            });
            cursorX += w2;
            hyphenated = true;
          }
        }
        if (!hyphenated) {
          // Walk back over any contiguous non-space fragments; the new token
          // is part of the same word as them (RTF often splits a single word
          // into many fragments — e.g. small-caps simulated by alternating
          // \fs18 / \fs14 chunks for each capital + rest-of-word). Wrapping
          // between those fragments would split a word in mid-word, like
          // "ADAPTOR, P" / "ROVIDER". Pull the leading partial word onto the
          // next line with this token.
          const carry = [];
          while (line.fragments.length) {
            const last = line.fragments[line.fragments.length - 1];
            if (last.kind === 'space') break;
            carry.unshift(line.fragments.pop());
            cursorX -= last.width;
          }
          commit('soft');
          for (const f of carry) {
            line.fragments.push(f);
            cursorX += f.width;
          }
        }
        // If hyphenation handled this token completely, skip the post-loop
        // fragment-push step.
        if (hyphenated) continue;
      }
      line.fragments.push({
        kind: isSpace ? 'space' : 'text', text: tok,
        font: seg.font, color: seg.color, backgroundColor: seg.backgroundColor,
        underline: seg.underline, strike: seg.strike,
        superscript: seg.superscript, subscript: seg.subscript,
        width: wRender, wrapWidth: w, ascent: m.ascent, descent: m.descent,
        fontAscent: m.fontAscent, fontDescent: m.fontDescent,
        naturalLineHeight: m.naturalLineHeight,
        wordLineHeight: m.wordLineHeight,
      });
      cursorX += w;
    }
  }
  // Final commit: only add the trailing line if it has content. Skip the
  // closing \par's empty placeholder when it follows a hard pageBreak —
  // Word/LibreOffice don't render that trailing empty line on the new
  // page. Without this, sample_04 page 2/4/6 day-header bars sit ~19
  // logical px below the reference. Pagination is preserved by the
  // schedule-row min-height floor (see layoutTableRow).
  const lastSeg = segs[segs.length - 1];
  const trailingEmptyAfterBreak = lastSeg && lastSeg.kind === 'pageBreak' && line.fragments.length === 0;
  if (!trailingEmptyAfterBreak) commit('hard');
  return lines;
}

function isSpaceToken(t) { return /^\s+$/.test(t); }
function isTrimmable(f) { return f.kind === 'space' && f.text !== '\t'; }

// Find the rightmost Knuth-Liang hyphenation point in `tok` such that
// (prefix + "-") fits within `availWidth`. Returns null when no breakpoint
// produces a fitting prefix. Letters at the boundary are stripped of any
// surrounding punctuation so the word's pattern lookup is clean; the
// punctuation comes back into the prefix unchanged.
function findHyphenSplit(tok, font, measure, availWidth) {
  // Strip leading/trailing non-letter punctuation so findHyphens sees a
  // clean word, but keep its offsets so we can map back to the original.
  let leading = 0, trailing = 0;
  while (leading < tok.length && !/[A-Za-z]/.test(tok[leading])) leading++;
  while (trailing < tok.length - leading && !/[A-Za-z]/.test(tok[tok.length - 1 - trailing])) trailing++;
  const word = tok.slice(leading, tok.length - trailing);
  if (word.length < 5) return null;
  const breaks = findHyphens(word);
  if (!breaks.length) return null;
  // Try break-points from longest-prefix to shortest, picking the first
  // that fits. Including the trailing "-" in the prefix measurement keeps
  // the printed line's width within budget.
  for (let i = breaks.length - 1; i >= 0; i--) {
    const off = breaks[i] + leading;
    const prefixText = tok.slice(0, off) + '-';
    const suffixText = tok.slice(off);
    const m = measure.measure(prefixText, font);
    const prefixWidth = m.width + (font.charSpacing || 0) * prefixText.length;
    if (prefixWidth <= availWidth) {
      const prefixRender = (m.rawWidth ?? m.width) + (font.charSpacing || 0) * prefixText.length;
      return { prefix: prefixText, suffix: suffixText, prefixWidth, prefixRender };
    }
  }
  return null;
}

function newLine() { return { fragments: [], width: 0, height: 0, ascent: 0, descent: 0 }; }

// Empirical line leading multiplier. Reference baseline-to-baseline distance
// is ~14 logical px (= 1.167 × the 12 px font) for body text. Word's "single"
// line spacing equals the font's design ascender + descender, which for most
// 12pt families ends up at roughly 1.15-1.20 × the em.
const LINE_LEADING = 1.25;

// Convert RTF line-spacing properties to a final advance (in CSS px) for one line.
// \sl/\slmult semantics:
//   - lineSpacing == 0 : auto / "single" — use the natural per-line leading.
//   - lineSpacing  > 0 with slmult==1 : multiplier of single-line spacing.
//                     (\sl240 == single, \sl360 == 1.5x, \sl480 == double)
//                     Word treats this as: ratio * (font's natural single-line height).
//   - lineSpacing  > 0 with slmult==0 : "at least N twips".
//   - lineSpacing  < 0                : exact -N twips.
function computeLineAdvance(line, paraState) {
  const sl = paraState.lineSpacing || 0;
  if (sl > 0 && paraState.lineSpacingMultiple) {
    // RTF \slmult1 means "multiple of 240ths of a single line". The "single
    // line" needs to use the same per-font leading that finalizeLine derives
    // for default-spacing paragraphs — otherwise \sl288\slmult1 (1.2× single)
    // produces a different pitch than the font's natural single-line × 1.2.
    // line.singleLineHeight is that font-specific single line.
    return (line.singleLineHeight || line.naturalHeight * 1.2) * (sl / 240);
  }
  if (sl > 0) {
    return Math.max(line.naturalHeight || line.height, twipsToPx(sl));
  }
  if (sl < 0) {
    return twipsToPx(-sl);
  }
  return line.height;
}

function finalizeLine(line, para) {
  let asc = 0, desc = 0, w = 0, maxFontSize = 0;
  let fontAsc = 0, fontDesc = 0;
  let maxNaturalLineHeight = 0;
  let maxWordLineHeight = 0;
  let dominantFamily = null;
  for (const f of line.fragments) {
    if (f.ascent > asc) asc = f.ascent;
    if (f.descent > desc) desc = f.descent;
    if (f.fontAscent > fontAsc) fontAsc = f.fontAscent;
    if (f.fontDescent > fontDesc) fontDesc = f.fontDescent;
    if (f.naturalLineHeight && f.naturalLineHeight > maxNaturalLineHeight) {
      maxNaturalLineHeight = f.naturalLineHeight;
    }
    if (f.wordLineHeight && f.wordLineHeight > maxWordLineHeight) {
      maxWordLineHeight = f.wordLineHeight;
    }
    if (f.font && f.font.sizePx > maxFontSize) {
      maxFontSize = f.font.sizePx;
      dominantFamily = f.font.family || null;
    }
    w += f.width || 0;
  }
  if (asc === 0) {
    // Empty paragraphs don't have runs to source their font size from. Prefer
    // any explicitly captured charState (set when the paragraph was finalized
    // with no runs) before falling back to the document default. Without this,
    // empty paragraphs render at 12pt even when the surrounding text is 10.5pt,
    // which inflates pagination.
    const fsHalfPt = para.charState?.fontSize ?? para.runs[0]?.charState?.fontSize ?? 24;
    const fs = halfPtToPx(fsHalfPt);
    asc = fs * 0.8; desc = fs * 0.2;
    // Use real font-design-metric ratios (Verdana/TNR/Cambria each return
    // ~1.05 ascent + ~0.25 descent at body sizes); the older 0.85/0.25
    // ratios under-counted height for empty paragraphs, leaving sample_01
    // page 3's medical image ~80 image px above its reference position.
    fontAsc = fs * 1.05; fontDesc = fs * 0.25;
    maxFontSize = fs;
  }
  const naturalHeight = asc + desc;
  // Word measures single-line height from the font's design metrics
  // (fontBoundingBox), not the per-glyph bounds. Use that for vertical
  // advance so our pagination tracks Word's. For smaller body text fonts,
  // Word adds extra leading (the LINE_LEADING multiplier kicks in); large
  // header/title fonts (≥18px) use just the design metrics or they end up
  // pushing body content down by an extra row of whitespace.
  const fontHeight = fontAsc + fontDesc;
  const useExtraLeading = maxFontSize < 14;
  // For TNR/Cambria at body sizes, Skia's fontBoundingBox over-shoots
  // LibreOffice's per-line advance by ~1 logical px (Skia returns 14 for
  // 9pt TNR; LibreOffice spaces lines at ~13.86). Tighten leading to
  // maxFontSize × 1.155 when the FIRST family in the run's CSS list is
  // one of those serifs — sample_06 page 2 +0.45% net even with a small
  // page 1 regression.
  // Per-(font,size) "single line height" — three-tier resolution:
  //   1. PRIMARY: empirical Word pitch (word-metrics.json) — measured
  //      directly from MS Word 2010 PDF refs. Most accurate.
  //   2. SECONDARY: OS/2 spec metric (font-metrics.json) — derived from
  //      the font binary's hhea/typo tables. Universal but slightly off
  //      for Word's small-body rendering (~1% drift).
  //   3. TERTIARY: Skia canvas fontBoundingBox + LINE_LEADING tweaks for
  //      small body sizes. Fallback when neither database has the font.
  // maxWordLineHeight is populated in the measurer with primary→secondary
  // resolution; here we just pick it up. Both \slmult1 and default-\sl=0
  // paths use the same metric (no more per-font hardcoded factors in
  // layout — all pushed into the data tables).
  const singleLineHeight =
    maxWordLineHeight ||
    maxNaturalLineHeight ||
    fontHeight ||
    (maxFontSize * 1.20);
  let leadingHeight;
  if (maxWordLineHeight) {
    leadingHeight = maxWordLineHeight;
  } else if (useExtraLeading) {
    // Tertiary fallback for small body sizes — used only when neither
    // metrics database knows the font. Same TNR/Cambria-vs-default split
    // we had before the databases existed.
    const firstFamily = dominantFamily ? dominantFamily.match(/^"?([^"\,]+)/)?.[1]?.trim() : null;
    const isTNRFamily = firstFamily && /^(Times New Roman|Cambria)$/i.test(firstFamily);
    if (isTNRFamily) {
      leadingHeight = Math.max(naturalHeight, maxFontSize * 1.155);
    } else {
      leadingHeight = Math.max(fontHeight, maxFontSize * LINE_LEADING);
    }
  } else {
    leadingHeight = fontHeight;
  }
  line.ascent = asc;
  line.descent = desc;
  line.fontAscent = fontAsc;
  line.fontDescent = fontDesc;
  line.naturalHeight = naturalHeight;
  line.height = Math.max(naturalHeight, leadingHeight);
  line.singleLineHeight = singleLineHeight;
  line.maxFontSize = maxFontSize;
  line.width = w;
}

function tokenize(text) {
  if (!text) return [];
  const out = [];
  let i = 0, n = text.length;
  while (i < n) {
    let j = i;
    if (/\s/.test(text[i])) {
      while (j < n && /\s/.test(text[j])) j++;
    } else {
      // word-level — treat hyphen as soft break point too
      while (j < n && !/\s/.test(text[j])) j++;
    }
    out.push(text.slice(i, j));
    i = j;
  }
  return out;
}

function drawLine(ctx, line, paraState, contentLeft, contentRight) {
  const lineWidthFull = contentRight - contentLeft;
  let xStart = contentLeft;
  const align = paraState.align || 'left';
  let extraSpace = 0;
  // Word doesn't justify lines that ended at a paragraph break or explicit \line —
  // only "soft-wrapped" continuation lines get full justification.
  const justify = align === 'justify' && line.softBreak;
  if (align === 'right') xStart = contentRight - line.width;
  else if (align === 'center') xStart = contentLeft + (lineWidthFull - line.width) / 2;
  else if (justify && line.width < lineWidthFull - 1 && countSpaces(line) > 0) {
    extraSpace = (lineWidthFull - line.width) / countSpaces(line);
  }

  // First-line indent already included by caller in contentLeft? Actually, breakIntoLines
  // doesn't include first-line indent; we handle here.
  if (paraState.indentFirst && line === undefined) { /* no-op */ }
  // (We're not tracking first-line vs continuation — for simplicity ignore indentFirst.)

  const baseline = ctx.page.cursorY + line.ascent;
  let x = xStart;

  for (const f of line.fragments) {
    if (f.kind === 'image') {
      ctx.page.items.push({
        type: 'image', x, y: baseline - f.height,
        w: f.width, h: f.height, image: f.image,
      });
      x += f.width;
    } else if (f.kind === 'space' || f.kind === 'text' || f.kind === 'pageNumPlaceholder') {
      // Tabs are 'space'-kind fragments but they have a fixed target column —
      // adding justify-extraSpace to the tab would push the bullet→body gap
      // wider than the intended \jclisttab\tx position, drifting the body
      // off-grid. Only widen *real* whitespace.
      const isTab = f.text === '\t';
      const wAdj = f.width + (f.kind === 'space' && !isTab && justify ? extraSpace : 0);
      if (f.backgroundColor && f.kind === 'text') {
        ctx.page.items.push({
          type: 'rect', x, y: ctx.page.cursorY, w: f.width, h: line.height,
          fill: f.backgroundColor,
        });
      }
      let dy = 0;
      if (f.superscript) dy = -(f.font.originalSize || f.font.sizePx) * 0.3;
      else if (f.subscript) dy = (f.font.originalSize || f.font.sizePx) * 0.15;
      if (f.text === '\t') {
        x += wAdj;
        continue;
      }
      ctx.page.items.push({
        type: f.kind === 'pageNumPlaceholder' ? 'pageNum' : 'text',
        x, y: baseline + dy,
        text: f.text, font: f.font, color: f.color,
        charSpacing: f.font.charSpacing || 0,
      });
      if (f.underline) {
        const ulY = baseline + Math.max(2, f.font.sizePx * 0.12);
        ctx.page.items.push({
          type: 'line', x1: x, y1: ulY, x2: x + f.width, y2: ulY,
          color: f.color, width: Math.max(1, f.font.sizePx * 0.06),
        });
      }
      if (f.strike) {
        const stY = baseline - f.font.sizePx * 0.3;
        ctx.page.items.push({
          type: 'line', x1: x, y1: stY, x2: x + f.width, y2: stY,
          color: f.color, width: Math.max(1, f.font.sizePx * 0.06),
        });
      }
      x += wAdj;
    }
  }
}

function countSpaces(line) {
  let n = 0;
  for (const f of line.fragments) if (f.kind === 'space' && f.text !== '\t') n++;
  return n;
}

// ---- Segments ----

// Split a string into runs of "lowercase" vs "non-lowercase" so a small-caps
// segment can render each part at the right size. Whitespace and punctuation
// stay with the surrounding chunk to keep the cursor's word boundary
// detection working — the wrapping logic only breaks at spaces.
function splitForSmallCaps(text) {
  const out = [];
  let start = 0;
  let lower = isLowerCaseLetter(text[0]);
  for (let i = 1; i < text.length; i++) {
    const isL = isLowerCaseLetter(text[i]);
    // Only flip on a true upper/lower boundary; non-letters carry over.
    if (text[i].match(/[a-zA-Z]/) && isL !== lower) {
      out.push({ text: text.slice(start, i), lower });
      start = i;
      lower = isL;
    }
  }
  out.push({ text: text.slice(start), lower });
  return out;
}

function isLowerCaseLetter(ch) {
  if (!ch) return false;
  return ch !== ch.toUpperCase() && ch === ch.toLowerCase();
}

function paragraphRunsToSegments(ctx, para) {
  const segs = [];
  const doc = ctx.doc;
  for (const run of para.runs) {
    const cs = run.charState;
    const font = resolveFont(doc, cs);
    const fc = resolveColor(doc, cs.foreColor) || DEFAULT_COLOR;
    const bg = (cs.highlight && cs.highlight > 0) ? resolveColor(doc, cs.highlight) : null;
    const baseSeg = {
      font,
      color: rgbToCss(fc),
      backgroundColor: bg ? rgbToCss(bg) : null,
      underline: !!cs.underline,
      strike: !!cs.strike,
      superscript: !!cs.superscript,
      subscript: !!cs.subscript,
      ascent: font.sizePx * 0.8,
      descent: font.sizePx * 0.2,
    };
    if (run.kind === 'image') {
      const im = run.image;
      let w = im.goalWidth ? twipsToPx(im.goalWidth) : (im.width || 100);
      let h = im.goalHeight ? twipsToPx(im.goalHeight) : (im.height || 100);
      if (im.scaleX && im.scaleX !== 100) w *= im.scaleX / 100;
      if (im.scaleY && im.scaleY !== 100) h *= im.scaleY / 100;
      w = Math.ceil(w);
      h = Math.ceil(h);
      segs.push({ kind: 'image', image: im, imageWidth: w, imageHeight: h });
    } else if (run.kind === 'br') segs.push({ kind: 'br' });
    else if (run.kind === 'pageBreak') segs.push({ kind: 'pageBreak' });
    else if (run.kind === 'tab') segs.push({ kind: 'tab', font, color: baseSeg.color, ascent: baseSeg.ascent, descent: baseSeg.descent });
    else if (run.kind === 'pageNum') segs.push({ ...baseSeg, kind: 'pageNum' });
    else {
      let text = run.text || '';
      if (cs.allcaps) text = text.toUpperCase();
      if (!text) continue;
      if (cs.smallcaps) {
        // Word's small caps: lowercase letters become uppercase rendered at
        // ~80% of the font size, uppercase stay full size. Implement by
        // splitting the run into alternating-case chunks, each its own
        // segment with the correct font size.
        for (const chunk of splitForSmallCaps(text)) {
          if (chunk.lower) {
            const smallFont = { ...font, sizePx: font.sizePx * 0.8 };
            segs.push({
              ...baseSeg,
              font: smallFont,
              ascent: smallFont.sizePx * 0.8,
              descent: smallFont.sizePx * 0.2,
              kind: 'text',
              text: chunk.text.toUpperCase(),
            });
          } else {
            segs.push({ ...baseSeg, kind: 'text', text: chunk.text });
          }
        }
      } else {
        segs.push({ ...baseSeg, kind: 'text', text });
      }
    }
  }
  return segs;
}

function resolveFont(doc, cs) {
  const entry = doc.fontTable.get(cs.fontIndex);
  // Use the document's named font directly. The system has the Microsoft
  // originals installed (Calibri, Cambria, Times New Roman, Arial, etc.),
  // so substituting metric-compatible clones would actively pull line break
  // decisions away from Word's. The familyFallback is only used if the
  // named font isn't available.
  //
  // RTF font tables sometimes embed the weight/style in the family name
  // ("Times New Roman Bold", "Arial Italic"). CSS treats those as opaque
  // family strings and doesn't match them to the same-family weight
  // variant the system has — Word, in contrast, is asking for the "bold
  // face of Times New Roman". Strip the trailing weight/style words so
  // the canvas can pair the family with the `\b` weight directly.
  const cleaned = entry && entry.name ? cleanFontName(entry.name) : null;
  const altName = entry && entry.altName ? cleanFontName(entry.altName) : null;
  // Mismatch heuristic: when the font name contradicts its family hint
  // (e.g. "DejaVu Sans" with \froman) AND there's no \*\falt anchor, the
  // document likely wasn't authored expecting that font on Word; both
  // LO and Word fall through to the family-hint substitute. When \falt
  // IS present we respect it as a third-tier fallback but keep the
  // literal name first — matches sample_02's mixed \f7 (no falt → TNR)
  // and \f8 (falt Arial → keeps Open Sans on systems that have it,
  // falls to Arial elsewhere) behavior.
  const familyMismatch = cleaned && entry && nameContradictsFamily(cleaned, entry.family);
  const skipNamed = familyMismatch && !altName;
  const fbChain = familyFallback(entry ? entry.family : 'roman');
  let family;
  if (!cleaned) {
    family = FALLBACK_FAMILY;
  } else if (skipNamed) {
    family = fbChain;
  } else if (altName) {
    family = `"${cleaned}", "${altName}", ${fbChain}`;
  } else {
    family = `"${cleaned}", ${fbChain}`;
  }
  let sizePx = halfPtToPx(cs.fontSize);
  const originalSize = sizePx;
  if (cs.superscript || cs.subscript) sizePx *= 0.65;
  return {
    family, sizePx, originalSize,
    bold: cs.bold, italic: cs.italic,
    superscript: cs.superscript, subscript: cs.subscript,
    charSpacing: cs.charSpacing ? cs.charSpacing / 20 : 0,
  };
}

function cleanFontName(name) {
  // Drop trailing weight/style words that some RTFs bake into the family
  // name (e.g. "Times New Roman Bold", "Arial Italic", "Helvetica Bold
  // Italic"). The actual weight comes from \b/\i on the run.
  return name.replace(/\s+(Bold|Italic|Oblique|Light|Regular|Medium|Heavy|Black|Semibold|Demibold|Thin)+$/gi, '').trim() || name;
}

// Detect when a font's display name contradicts its \fnil/\froman/\fswiss/etc
// family hint. Sample_02's font table has \f7 \froman "DejaVu Sans" — the
// "Sans" suffix contradicts the roman/serif family hint. Such mismatches
// indicate the document author / authoring tool emitted the family hint as
// a generic fallback target, distinct from the literal font name. When the
// entry also lacks an \*\falt anchor, LibreOffice falls through to the
// family hint instead of rendering the literal font, which is what makes
// sample_02's body render as serif on the reference machine.
function nameContradictsFamily(cleanedName, familyHint) {
  if (!cleanedName || !familyHint) return false;
  const n = cleanedName.toLowerCase();
  // Conservative test: we only flag a contradiction when the name explicitly
  // contains "Sans" / "Serif" / "Mono" *as a word*, not when it merely
  // belongs to a family alias. "Verdana" / "Arial" / "Tahoma" don't carry
  // "sans" in their name and shouldn't trigger fallback even though they're
  // sans-serif faces — sample_01 uses \froman Verdana intentionally and
  // expects Verdana to render, not the family-hint fallback.
  const hasSans = /\bsans\b/.test(n);
  const hasSerif = /\bserif\b/.test(n);
  const hasMono = /\bmono\b/.test(n);
  if (familyHint === 'roman' && hasSans && !hasSerif) return true;
  if (familyHint === 'swiss' && hasSerif && !hasSans) return true;
  if (familyHint === 'modern' && !hasMono) return false;
  return false;
}

function familyFallback(family) {
  // The Liberation/Carlito families are metric-compatible substitutes for
  // Times New Roman / Arial / Calibri. On systems where the Microsoft fonts
  // aren't installed (most Linux/headless Chromium setups) they keep
  // line-break decisions close to Word's, which is the single biggest lever
  // for cross-engine pixel similarity.
  switch (family) {
    case 'roman': return '"Times New Roman", "Liberation Serif", serif';
    case 'swiss': return 'Arial, "Liberation Sans", "Carlito", Helvetica, sans-serif';
    case 'modern': return '"Courier New", "Liberation Mono", monospace';
    case 'script': return '"Comic Sans MS", cursive';
    case 'decor': return 'serif';
    case 'tech': return 'monospace';
    default: return 'serif';
  }
}

function resolveColor(doc, idx) {
  if (idx === undefined || idx === null || idx < 0) return null;
  const c = doc.colorTable[idx];
  return c || null;
}

// ---- Tables ----

function layoutTable(ctx, table) {
  if (!table.rows.length) return;
  // Each row carries its own \cellx edges — Word RTF tables routinely vary the
  // column count and widths from row to row (e.g., a 1-cell header row
  // followed by 3-cell data rows). Honoring per-row edges, not the first
  // row's, is what makes sample_04's three-column schedule render correctly
  // instead of collapsing every row into the first row's single column.
  for (const row of table.rows) {
    const tblLeft = ctx.page.contentLeft + twipsToPx(row.state.left || 0);
    const cellEdges = (row.state.cellEdges || []).map(t => twipsToPx(t));
    layoutTableRow(ctx, row, tblLeft, cellEdges);
  }
}

function layoutTableRow(ctx, row, tblLeft, cellEdges) {
  const cells = row.cells;
  if (cells.length === 0) return;
  // Row-level defaults from \trpaddl/r/t/b. Per-cell \clpadl/r/t/b can
  // override these per cell.
  const rowPadL = twipsToPx(row.state.pad?.l || 0);
  const rowPadR = twipsToPx(row.state.pad?.r || 0);
  const rowPadT = twipsToPx(row.state.pad?.t || 0);
  const rowPadB = twipsToPx(row.state.pad?.b || 0);

  const edges = [tblLeft];
  for (let i = 0; i < cellEdges.length; i++) {
    edges.push(tblLeft + cellEdges[i] - twipsToPx(row.state.left || 0));
  }

  const cellLines = [];
  // \trrhN: positive = exact, negative = at-least. We treat both as a MINIMUM
  // — content always grows the row when needed, but for tall \trrh-3600
  // sample_04 rows ("Celebração" header), Math.abs gives the proper floor
  // instead of a negative seed that gets clobbered by the first cell.
  let rowHeight = twipsToPx(Math.abs(row.state.height || 0));
  // Some LibreOffice-emitted tables (sample_04 schedule grids) rely on
  // implicit row height = ~2.1× the largest cell font. Without this floor
  // schedule rows pack ~30 entries/page vs the reference's ~22, collapsing
  // 7 pages of content into 5. Only apply when the row has actual text
  // content — "spacer" rows (\trrh-1 with empty cells, used as padding
  // between table sections) must stay near-zero or they balloon the
  // header strip 5×.
  let largestRowFontSize = 0;
  let rowHasText = false;
  for (const c of cells) {
    for (const block of (c.blocks || [])) {
      if (block.kind !== 'paragraph') continue;
      for (const run of (block.runs || [])) {
        if (run.kind === 'text' && (run.text || '').length > 0) {
          rowHasText = true;
          const fs = run.charState?.fontSize || 0;
          if (fs > largestRowFontSize) largestRowFontSize = fs;
        }
      }
    }
  }
  // Schedule-row floor: body-sized text gets ~2.15× the font; heading rows
  // (≥11pt — sample_04's gold/black day banners use 12pt bold) get a
  // smaller multiplier (1.7×) just enough to leave centering slack so the
  // cell text can vertically center within the band rather than sticking
  // to the top edge. Empirical match to LibreOffice's reference render.
  if (rowHasText && largestRowFontSize > 0) {
    // Detect "uniformly-shaded footer rows" (sample_04's names + Grupo
    // strip): every cell carries shading. Sample_01's table cells are
    // unshaded so this gate doesn't catch them. For those footer rows the
    // ref renders ~1 logical px tighter per row, accumulating enough to
    // make the last (Grupo) row spill onto the next page when we use the
    // 2.15× body multiplier. Drop to 2.05× ONLY for the all-shaded case
    // where small-font (<18 hp ≈ 9pt) text is the dominant element.
    // Discriminate sample_04-style schedule tables from sample_01's nested
    // medical-report tables via \trleft sign: sample_04 emits \trleft-10
    // on every row (the negative offset makes the table extend slightly
    // left of \margl); sample_01 uses positive \trleft values
    // (1054/110/115). The negative-offset pattern correlates strongly with
    // LibreOffice's "compressed schedule grid" rendering, where each row
    // needs ~1 logical px less floor than a generic 2.15× rule produces —
    // enough drift over ~20 rows to push the Grupo footer onto a blank
    // overflow page. Tightening the multiplier ONLY for these rows fixes
    // the overflow without touching sample_01 (whose trleft is positive).
    const isCompressedTable = (row.state.left || 0) < 0;
    let mult;
    if (largestRowFontSize >= 22) mult = 1.7;
    else if (isCompressedTable && largestRowFontSize < 18) mult = 2.05;
    else if (isCompressedTable) mult = 2.08;
    else mult = 2.15;
    const minRowH = halfPtToPx(largestRowFontSize) * mult;
    if (minRowH > rowHeight) rowHeight = minRowH;
  }
  for (let i = 0; i < cells.length; i++) {
    const cellInfo = cells[i].info || {};
    let padL = cellInfo.pad?.l !== undefined ? twipsToPx(cellInfo.pad.l) : rowPadL;
    let padR = cellInfo.pad?.r !== undefined ? twipsToPx(cellInfo.pad.r) : rowPadR;
    let padT = cellInfo.pad?.t !== undefined ? twipsToPx(cellInfo.pad.t) : rowPadT;
    let padB = cellInfo.pad?.b !== undefined ? twipsToPx(cellInfo.pad.b) : rowPadB;
    // For LibreOffice nested-table-emitted frames, the nested cell's padding
    // adds to the OUTER cell's effective padding — the visible "box" sits
    // inside the outer cell with the nested cell's own pad inside the box.
    // Matches the QUANTIFICATION grid in sample_01 page 3 where each row is
    // ~70 image px tall (vs ~25 px without nested padding accounted for).
    // The factor 2× empirically gets row height ~50 logical px to match
    // LibreOffice's vertical-center band behavior on those cells.
    const nf = cellInfo.nestedFrame;
    if (nf && (nf.padL || nf.padR || nf.padT || nf.padB)) {
      padL += twipsToPx(nf.padL || 0);
      padR += twipsToPx(nf.padR || 0);
      padT += twipsToPx(nf.padT || 0) * 3;
      padB += twipsToPx(nf.padB || 0) * 3;
    }
    const x0 = (edges[i] || tblLeft) + padL;
    const x1 = (edges[i + 1] || x0 + 100) - padR;
    const widthAvail = Math.max(20, x1 - x0);
    let yLocal = padT;
    // yLocalCenter tracks the cell content height for VERTICAL CENTERING.
    // Word centers cells using a metric that's close to the font's
    // cap-height (≈ 0.7 × fontSize), NOT the full fontAscent+fontDescent
    // and NOT the per-glyph natural bounds. Using fontHeight or natural
    // bounds leaves zero (or tiny) slack in single-line banner rows
    // because the line's full ascent+descent box fills the entire content
    // area, leaving the visual glyph stuck at the top edge.
    //
    // Empirical: sample_04 day banner ("quinta-feira" / "Reunião do meio
    // de semana") with fontHeight as contentH gave slack=0 → text at
    // padT+0; reference shows ~6 logical px of slack/2 = text centered
    // visually. 0.7 × fontSize gives slack/2 ≈ 5.5 logical px which lands
    // text top at ~30 image px from band top vs reference's 32 image px.
    let yLocalCenter = padT;
    const blockData = [];
    // Detect cells that contain ONLY empty paragraphs (no text runs). These
    // are spacer rows (\trrh-1 with empty blocks, used as thin separators
    // between table sections). LibreOffice/Word collapses them to a near-
    // zero band; growing them by full empty-line height adds ~20 logical
    // px per page break and pushes day-header bars off-position.
    let cellHasText = false;
    for (const block of cells[i].blocks) {
      if (block.kind !== 'paragraph') continue;
      for (const run of (block.runs || [])) {
        if (run.kind === 'text' && (run.text || '').length > 0) cellHasText = true;
      }
    }
    for (const block of cells[i].blocks) {
      if (block.kind === 'paragraph') {
        const lines = breakIntoLines(ctx, block, widthAvail);
        blockData.push({ state: block.state, lines });
        yLocal += twipsToPx(block.state.spaceBefore || 0);
        yLocalCenter += twipsToPx(block.state.spaceBefore || 0);
        if (cellHasText) {
          for (const l of lines) {
            if (l.pageBreak) continue;
            yLocal += computeLineAdvance(l, block.state);
            // For centering, treat each line as occupying ~0.85 × its
            // dominant font size. That's roughly cap-height (~0.7) plus
            // descent allowance (~0.15) for Latin sans/serif. Pure
            // cap-height (0.7) lets descenders dangle below the
            // centered cap-band, leaving text visually anchored to the
            // band BOTTOM. 0.85 shifts text top up by ~1 logical px
            // while keeping descenders within the band — closer to the
            // visually-centered look on Word's schedule banner rows.
            const fs = (l.maxFontSize || (l.fontAscent + l.fontDescent) || 16);
            yLocalCenter += fs * 0.85;
          }
        }
        yLocal += twipsToPx(block.state.spaceAfter || 0);
        // spaceAfter is paragraph-level extra space — don't include in the
        // visual-center metric or it'll bias the text upward.
      }
    }
    yLocal += padB;
    yLocalCenter += padB;
    cellLines.push({ x0, x1, blockData, height: yLocal, centerHeight: yLocalCenter, padL, padR, padT, padB });
    if (yLocal > rowHeight) rowHeight = yLocal;
  }

  if (ctx.page.cursorY + rowHeight > ctx.page.contentBottom) {
    pageBreak(ctx);
  }
  const yTop = ctx.page.cursorY;

  for (let i = 0; i < cellLines.length; i++) {
    const cl = cellLines[i];
    const cell = cells[i];
    const x0 = cl.x0 - cl.padL, x1 = cl.x1 + cl.padR;

    // Cell shading: \clshdngN is the percentage (0-10000) of \clcfpat (foreground)
    // mixed over \clcbpat (background). 10000 = 100% foreground, 0 = 100% background.
    // Most schedule tables (sample_04) use \clcfpatN\clshdng10000 to fill the cell
    // with the named color; older docs use \clcbpat for the same effect.
    const fillColor = resolveShadingColor(ctx.doc.colorTable, cell.info);
    if (fillColor) {
      ctx.page.items.push({ type: 'rect', x: x0, y: yTop, w: x1 - x0, h: rowHeight, fill: fillColor });
    }
    // For LibreOffice-emitted nested-table border frames (sample_01 page 3),
    // the visible box sits inside the outer cell with padding-sized gaps on
    // every side. Inset the border by the nested cell's recorded padding
    // (clpadl/r/t/b on the nested table) so adjacent outer cells render as
    // separate framed boxes instead of a unified grid.
    let bx0 = x0, bx1 = x1, by0 = yTop, by1 = yTop + rowHeight;
    const nf = cell.info && cell.info.nestedFrame;
    if (nf && (nf.padL || nf.padR || nf.padT || nf.padB)) {
      bx0 += twipsToPx(nf.padL);
      bx1 -= twipsToPx(nf.padR);
      by0 += twipsToPx(nf.padT);
      by1 -= twipsToPx(nf.padB);
    }
    drawCellBorders(ctx, cell.info, bx0, by0, bx1, by1);

    // Vertical alignment within the cell: \clvertalc centers content,
    // \clvertalb bottom-aligns, default (\clvertalt) is top.  When the
    // row's height exceeds the content's natural extent (common for
    // sample_04's schedule rows where the row floor is 2.15 × the font),
    // un-aligned content sticks to the top, leaving an empty bottom band.
    // Compute the actual content height and shift the start y downward.
    //
    // For \clvertalc specifically, use the FONT-design height rather than
    // the per-glyph natural bounds. Word centers text using typographic
    // metrics — two cells in the same row with the same font + size align
    // at the same y regardless of whether one contains a tilde-bearing
    // character and the other doesn't. Sample_04's day banner row
    // ("quinta-feira" + "Reunião do meio de semana") needs this; without
    // it, the tilde on "ã" inflates the second cell's naturalHeight by
    // ~4 px, pulling its centered y up and creating a visible misalignment.
    const vAlign = cell.info && cell.info.vAlign;
    let y = yTop + cl.padT;
    if (vAlign === 'center' || vAlign === 'bottom') {
      // For centering, use the cap-height-approximated content height
      // (cl.centerHeight); for bottom-align, use the full layout height
      // (cl.height) since we want the visible glyph extent to sit on the
      // bottom edge.
      const heightForCenter = vAlign === 'center'
        ? (cl.centerHeight ?? cl.height)
        : cl.height;
      const contentH = heightForCenter - cl.padT - cl.padB;
      const slack = (rowHeight - cl.padT - cl.padB) - contentH;
      if (slack > 0.5) {
        y += vAlign === 'center' ? slack / 2 : slack;
      }
    }
    for (const blk of cl.blockData) {
      ctx.page.cursorY = y + twipsToPx(blk.state.spaceBefore || 0);
      for (const line of blk.lines) {
        if (line.pageBreak) continue;
        drawLine(ctx, line, blk.state, cl.x0, cl.x1);
        ctx.page.cursorY += computeLineAdvance(line, blk.state);
      }
      ctx.page.cursorY += twipsToPx(blk.state.spaceAfter || 0);
      y = ctx.page.cursorY;
    }
  }
  ctx.page.cursorY = yTop + rowHeight;
}

function resolveShadingColor(colorTable, info) {
  if (!info) return null;
  const fg = info.shadingFg !== undefined ? colorTable[info.shadingFg] : null;
  const bg = info.shadingBg !== undefined ? colorTable[info.shadingBg] : null;
  // Legacy field set directly by older callers (e.g., paragraph shading).
  const legacy = info.shadingColor !== undefined ? colorTable[info.shadingColor] : null;
  const shading = info.shading; // 0..10000

  // Pattern-only (no \clshdng) means Word fills with the background pattern at
  // 0% — i.e., no visible shading. Solid fills always pair the pattern with
  // \clshdng10000. Treating bare \clcfpat as a fill drew rectangles on every
  // bordered cell in sample_04 and tanked the score. The legacy field
  // (shadingColor) bypasses the percentage check to preserve sample_06's
  // paragraph shading behavior.
  if (shading === undefined) {
    return legacy ? rgbToCss(legacy) : null;
  }
  if (shading >= 9000) return fg ? rgbToCss(fg) : (bg ? rgbToCss(bg) : null);
  if (shading <= 100) return bg ? rgbToCss(bg) : null;
  const a = shading / 10000;
  const f = fg || { r: 0, g: 0, b: 0 };
  const b = bg || { r: 255, g: 255, b: 255 };
  return rgbToCss({
    r: Math.round(f.r * a + b.r * (1 - a)),
    g: Math.round(f.g * a + b.g * (1 - a)),
    b: Math.round(f.b * a + b.b * (1 - a)),
  });
}

function drawCellBorders(ctx, info, x0, y0, x1, y1) {
  if (!info) return;
  const draw = (b, X1, Y1, X2, Y2) => {
    // Only draw borders that have an explicit style. \brdrnone-marked borders
    // and bare \clbrdr* (no style) should leave no line.
    if (!b || !b.style || b.style === 'none') return;
    // \brdrwN is the border width in twips per RTF spec. twipsToPx maps it
    // directly to logical px (e.g. \brdrw40 → 2.67 logical). Earlier
    // we divided by 4 here, which made every border ~4× too thin. Even
    // raw twipsToPx slightly OVERSHOOTS what ref renders at higher
    // widths — sample_04's \brdrw40 ref-line is ~11 PNG-px tall (a hair
    // under 3 logical), and Skia's 2.67 lineWidth with anti-aliasing
    // bleeds to ~12 PNG. The factor 0.85 lands the rendered line within
    // ~1 PNG-px of ref while still giving enough thickness to match
    // visually-thick section underlines.
    const w = b.width ? Math.max(0.5, twipsToPx(b.width) * 0.85) : 0.75;
    const color = (b.color && ctx.doc.colorTable[b.color])
      ? rgbToCss(ctx.doc.colorTable[b.color]) : '#000';
    ctx.page.items.push({ type: 'line', x1: X1, y1: Y1, x2: X2, y2: Y2, color, width: w });
  };
  draw(info.borderTop, x0, y0, x1, y0);
  draw(info.borderBottom, x0, y1, x1, y1);
  draw(info.borderLeft, x0, y0, x0, y1);
  draw(info.borderRight, x1, y0, x1, y1);
}

// ---- Page numbers ----

function resolvePageNumbers(pages) {
  for (let i = 0; i < pages.length; i++) {
    const pg = pages[i];
    for (const item of pg.items) {
      if (item.type === 'pageNum') {
        item.type = 'text';
        item.text = String(i + 1);
      }
    }
  }
}

// ===== renderer.js =====
// Canvas renderer: draws a list of pages produced by the layout engine onto
// individual <canvas> elements appended to a host DOM element.
function renderPages(pages, hostElement, options = {}) {
  const dpr = options.devicePixelRatio || (typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1);
  const fillBg = options.background ?? '#ffffff';

  while (hostElement.firstChild) hostElement.removeChild(hostElement.firstChild);
  hostElement.style.display = 'flex';
  hostElement.style.flexDirection = 'column';
  hostElement.style.alignItems = 'center';
  hostElement.style.gap = '16px';

  const renderedCanvases = [];
  const imagePromises = [];
  for (let i = 0; i < pages.length; i++) {
    const page = pages[i];
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(page.width * dpr);
    canvas.height = Math.round(page.height * dpr);
    canvas.style.width = page.width + 'px';
    canvas.style.height = page.height + 'px';
    canvas.style.boxShadow = '0 1px 3px rgba(0,0,0,.15)';
    canvas.style.background = fillBg;
    canvas.dataset.page = String(i + 1);
    hostElement.appendChild(canvas);

    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.fillStyle = fillBg;
    ctx.fillRect(0, 0, page.width, page.height);

    drawItems(ctx, page.items, imagePromises);
    renderedCanvases.push(canvas);
  }
  // Expose a Promise that resolves once all images have settled
  renderedCanvases.imagesReady = Promise.all(imagePromises);
  return renderedCanvases;
}

function drawItems(ctx, items, imagePromises) {
  for (const item of items) {
    if (item.type === 'rect') {
      ctx.fillStyle = item.fill || '#000';
      ctx.fillRect(item.x, item.y, item.w, item.h);
    } else if (item.type === 'ellipse') {
      const cx = item.x + item.w / 2;
      const cy = item.y + item.h / 2;
      const rx = item.w / 2;
      const ry = item.h / 2;
      ctx.beginPath();
      ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
      if (item.fill) {
        ctx.fillStyle = item.fill;
        ctx.fill();
      }
      if (item.stroke) {
        ctx.strokeStyle = item.stroke;
        ctx.lineWidth = item.strokeW || 1;
        ctx.stroke();
      }
    } else if (item.type === 'rect-stroke') {
      // Stroked rectangle outline — used for full page borders so corners
      // miter cleanly. lineJoin="miter" makes the corners sharp 90° joins
      // (matches Word's page border).
      ctx.beginPath();
      ctx.strokeStyle = item.color || '#000';
      ctx.lineWidth = item.width || 1;
      ctx.lineJoin = 'miter';
      ctx.miterLimit = 4;
      ctx.strokeRect(item.x, item.y, item.w, item.h);
    } else if (item.type === 'line') {
      ctx.beginPath();
      ctx.strokeStyle = item.color || '#000';
      ctx.lineWidth = item.width || 1;
      // Dashed / dotted / dash-dot border styles. Pattern lengths scale
      // with line width so thin borders aren't dotted at sub-pixel pace.
      const w = item.width || 1;
      let dash = null;
      switch (item.style) {
        case 'dotted': dash = [w, w * 1.5]; break;
        case 'dashed': dash = [w * 4, w * 2]; break;
        case 'dashdot': dash = [w * 4, w * 2, w, w * 2]; break;
        case 'dashdotdot': dash = [w * 4, w * 2, w, w * 2, w, w * 2]; break;
        case 'hair': dash = [w, w]; break;
      }
      if (dash) ctx.setLineDash(dash); else ctx.setLineDash([]);
      ctx.moveTo(item.x1, item.y1);
      ctx.lineTo(item.x2, item.y2);
      ctx.stroke();
      ctx.setLineDash([]);
    } else if (item.type === 'text') {
      drawText(ctx, item);
    } else if (item.type === 'image') {
      imagePromises.push(new Promise(resolve => drawImage(ctx, item, resolve)));
    }
  }
}

function drawText(ctx, item) {
  const f = item.font;
  const style = f.italic ? 'italic ' : '';
  const weight = f.bold ? '700 ' : '400 ';
  ctx.font = `${style}${weight}${f.sizePx}px ${f.family || FALLBACK_FAMILY}`;
  ctx.fillStyle = item.color || '#000';
  ctx.textBaseline = 'alphabetic';
  if (item.charSpacing && item.charSpacing > 0.05) {
    // manual letter-spacing
    let x = item.x;
    for (const ch of item.text) {
      ctx.fillText(ch, x, item.y);
      x += ctx.measureText(ch).width + item.charSpacing;
    }
  } else {
    ctx.fillText(item.text, item.x, item.y);
  }
}

function drawImage(ctx, item, done) {
  const im = item.image;
  if (!im || !im.dataUrl) {
    // unsupported placeholder
    ctx.save();
    ctx.fillStyle = '#f0f0f0';
    ctx.fillRect(item.x, item.y, item.w, item.h);
    ctx.strokeStyle = '#bbb';
    ctx.strokeRect(item.x, item.y, item.w, item.h);
    ctx.fillStyle = '#777';
    ctx.font = '12px sans-serif';
    ctx.fillText('[image]', item.x + 6, item.y + 16);
    ctx.restore();
    done();
    return;
  }
  const img = new Image();
  img.onload = () => {
    try { ctx.drawImage(img, item.x, item.y, item.w, item.h); } catch (e) {}
    done();
  };
  img.onerror = () => done();
  img.src = im.dataUrl;
}

// ===== index.js =====
// rtfjs - public entry point.
// Usage:
//   import { RTFRenderer } from './src/index.js';
//   RTFRenderer.render(rtfString, document.getElementById('container'));
//
// The library injects one <canvas> per page, stacked vertically inside the host element.
const RTFRenderer = {
  render(rtfString, hostElement, options = {}) {
    if (typeof rtfString !== 'string') throw new TypeError('rtfString must be a string');
    if (!hostElement) throw new TypeError('hostElement is required');

    const builder = new DocumentBuilder();
    parse(rtfString, builder);
    const doc = builder.build();
    const pages = layoutDocument(doc, options);
    const canvases = renderPages(pages, hostElement, options);

    return {
      pageCount: pages.length,
      canvases,
      document: doc,
      pages,
      imagesReady: canvases.imagesReady,
    };
  },

  // Lower-level utilities (handy for testing and building custom UIs)
  parse(rtfString) {
    const builder = new DocumentBuilder();
    parse(rtfString, builder);
    return builder.build();
  },
  layout(doc, options) { return layoutDocument(doc, options); },
};

// Provide a UMD-style global if loaded directly via <script>
if (typeof window !== 'undefined') {
  // Don't overwrite if user already defined one
  if (!window.RTFRenderer) window.RTFRenderer = RTFRenderer;
}
RTFRenderer;

  // expose
  global.RTFRenderer = RTFRenderer;
})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : this));
