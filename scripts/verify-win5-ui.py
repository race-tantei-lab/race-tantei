#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "src" / "public-site-entry-v28.ts"
PARENT = ROOT / "src" / "public-site-entry-v27.ts"
WRANGLER = ROOT / "wrangler.jsonc"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    entry = ENTRY.read_text(encoding="utf-8")
    parent = PARENT.read_text(encoding="utf-8")
    source = entry + "\n" + parent
    wrangler = WRANGLER.read_text(encoding="utf-8")

    require('"main": "src/public-site-entry-v28.ts"' in wrangler, "WIN5_V28_NOT_CANONICAL_ENTRY")
    require('class="nav-win5"' in parent, "WIN5_TOP_NAV_TAB_MISSING")
    require('<nav class="nav"><a href="/">レース</a>' in parent, "WIN5_TOP_NAV_INSERTION_ANCHOR_MISSING")
    require('aria-current="page"' in parent, "WIN5_ACTIVE_TOP_NAV_STATE_MISSING")
    require('position:fixed' not in source, "WIN5_FLOATING_BUTTON_STYLE_REINTRODUCED")
    require('win5-global-link' in parent and '.replace(' in parent, "WIN5_LEGACY_FLOAT_REMOVAL_MISSING")

    require('data-win5-tab="tickets"' in entry and '>買い目</button>' in entry, "WIN5_TICKETS_VIEW_BUTTON_MISSING")
    require('data-win5-tab="other"' in entry and '>その他</button>' in entry, "WIN5_OTHER_VIEW_BUTTON_MISSING")
    require("activate('tickets')" in entry, "WIN5_TICKETS_VIEW_NOT_DEFAULT")
    require("ticketsPanel.hidden = !ticketsActive" in entry and "otherPanel.hidden = ticketsActive" in entry, "WIN5_EXCLUSIVE_VIEW_SWITCH_MISSING")
    require("otherPanel.append(diagnosticsSection)" in entry, "WIN5_DIAGNOSTICS_NOT_MOVED_TO_OTHER")
    require("otherPanel.append(quick)" in entry and "otherPanel.append(note)" in entry, "WIN5_METADATA_NOT_MOVED_TO_OTHER")
    require("ticketsPanel.append(section)" in entry, "WIN5_PRIMARY_CONTENT_NOT_GROUPED_IN_TICKETS")

    require('3パターン比較' in parent and '買い目' in parent, "WIN5_PRIMARY_INFORMATION_ORDER_MISSING")
    require('各レースの1着確率・学習情報を見る' in parent, "WIN5_DIAGNOSTICS_COLLAPSE_MISSING")
    require('.win5-target-list' in parent and '.win5-ticket-row' in parent, "WIN5_MOBILE_VERTICAL_LAYOUT_MISSING")
    require('overflow-x:auto' not in source, "WIN5_HORIZONTAL_SCROLL_REINTRODUCED")

    print("WIN5_UI_OK top_nav=true floating_button=false view_switch=tickets_other default=tickets diagnostics=other horizontal_scroll=false")


if __name__ == "__main__":
    main()
