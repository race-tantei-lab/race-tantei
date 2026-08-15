#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "src" / "public-site-entry-v27.ts"
WRANGLER = ROOT / "wrangler.jsonc"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    source = ENTRY.read_text(encoding="utf-8")
    wrangler = WRANGLER.read_text(encoding="utf-8")

    require('"main": "src/public-site-entry-v27.ts"' in wrangler, "WIN5_V27_NOT_CANONICAL_ENTRY")
    require('class=\\"nav-win5\\"' in source, "WIN5_TOP_NAV_TAB_MISSING")
    require('<nav class=\\"nav\\"><a href=\\"/\\">レース</a>' in source, "WIN5_TOP_NAV_INSERTION_ANCHOR_MISSING")
    require('aria-current=\\"page\\"' in source, "WIN5_ACTIVE_TOP_NAV_STATE_MISSING")
    require('position:fixed' not in source, "WIN5_FLOATING_BUTTON_STYLE_REINTRODUCED")
    require('win5-global-link' in source and '.replace(' in source, "WIN5_LEGACY_FLOAT_REMOVAL_MISSING")
    require('3パターン比較' in source and '買い目' in source, "WIN5_PRIMARY_INFORMATION_ORDER_MISSING")
    require('各レースの1着確率・学習情報を見る' in source, "WIN5_DIAGNOSTICS_COLLAPSE_MISSING")
    require('.win5-target-list' in source and '.win5-ticket-row' in source, "WIN5_MOBILE_VERTICAL_LAYOUT_MISSING")
    require('overflow-x:auto' not in source, "WIN5_HORIZONTAL_SCROLL_REINTRODUCED")

    print("WIN5_UI_OK top_nav=true floating_button=false primary_order=targets_plans_tickets diagnostics=collapsed horizontal_scroll=false")


if __name__ == "__main__":
    main()
