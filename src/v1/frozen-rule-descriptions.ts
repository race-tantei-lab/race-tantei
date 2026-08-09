import { TANSYO_RULES } from "./frozen-rules-tansyo.js";
import { UMAREN_RULES } from "./frozen-rules-umaren.js";
import { WIDE_RULES } from "./frozen-rules-wide.js";
import { UMATAN_RULES } from "./frozen-rules-umatan.js";
import { SANRENPUKU_RULES } from "./frozen-rules-sanrenpuku.js";
import { SANRENTAN_RULES } from "./frozen-rules-sanrentan.js";

export const FROZEN_RULE_DESCRIPTIONS: Record<string, readonly string[]> = {
  "単勝": TANSYO_RULES,
  "馬連": UMAREN_RULES,
  "ワイド": WIDE_RULES,
  "馬単": UMATAN_RULES,
  "3連複": SANRENPUKU_RULES,
  "3連単": SANRENTAN_RULES
};

export const FROZEN_RULE_COUNT = Object.values(FROZEN_RULE_DESCRIPTIONS).reduce((sum, rows) => sum + rows.length, 0);
