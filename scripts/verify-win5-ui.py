#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "src" / "public-site-entry-v30.ts"
DEADLINE = ROOT / "src" / "public-site-entry-v29.ts"
ENTRY = ROOT / "src" / "public-site-entry-v28.ts"
PARENT = ROOT / "src" / "public-site-entry-v27.ts"
WRANGLER = ROOT / "wrangler.jsonc"
RUNTIME = ROOT / "src" / "v1" / "completed-win5.ts"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    canonical = CANONICAL.read_text(encoding="utf-8")
    deadline = DEADLINE.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    parent = PARENT.read_text(encoding="utf-8")
    source = canonical + "\n" + deadline + "\n" + entry + "\n" + parent
    wrangler = WRANGLER.read_text(encoding="utf-8")
    runtime = RUNTIME.read_text(encoding="utf-8")

    require('"main": "src/public-site-entry-v30.ts"' in wrangler, "WIN5_V30_NOT_CANONICAL_ENTRY")
    require('import publicSite from "./public-site-entry-v29.js"' in canonical, "WIN5_V30_V29_WRAPPER_MISSING")
    require('import publicSite from "./public-site-entry-v28.js"' in deadline, "WIN5_V29_V28_WRAPPER_MISSING")
    require('class="nav-win5"' in parent, "WIN5_TOP_NAV_TAB_MISSING")
    require('<nav class="nav"><a href="/">レース</a>' in parent, "WIN5_TOP_NAV_INSERTION_ANCHOR_MISSING")
    require('aria-current="page"' in parent, "WIN5_ACTIVE_TOP_NAV_STATE_MISSING")
    require('position:fixed' not in source, "WIN5_FLOATING_BUTTON_STYLE_REINTRODUCED")
    require('win5-global-link' in parent and '.replace(' in parent, "WIN5_LEGACY_FLOAT_REMOVAL_MISSING")

    require('data-win5-tab="tickets"' in entry and '>買い目</button>' in entry, "WIN5_TICKETS_VIEW_BUTTON_MISSING")
    require('data-win5-tab="other"' in entry and '>その他</button>' in entry, "WIN5_OTHER_VIEW_BUTTON_MISSING")
    require("activate('tickets')" in entry, "WIN5_TICKETS_VIEW_NOT_DEFAULT")
    require("ticketsPanel.hidden = !ticketsActive" in entry and "otherPanel.hidden = ticketsActive" in entry, "WIN5_EXCLUSIVE_VIEW_SWITCH_MISSING")

    require("if (plansSection) plansSection.remove()" in entry, "WIN5_DUPLICATE_PLAN_COMPARISON_NOT_REMOVED")
    require("for (const section of [targetSection, ticketsSection])" in entry, "WIN5_TICKET_VIEW_ORDER_INVALID")
    require("[targetSection, plansSection, ticketsSection]" not in entry, "WIN5_DUPLICATE_PLAN_COMPARISON_REINTRODUCED")

    require("label === 'ルール'" in entry and "card.remove()" in entry, "WIN5_RULE_CARD_NOT_REMOVED")
    require("if (note) note.remove()" in entry, "WIN5_RULE_NOTE_NOT_REMOVED")
    require("otherPanel.append(note)" not in entry, "WIN5_RULE_NOTE_REINTRODUCED")
    require("grid-template-columns:repeat(2,minmax(0,1fr))" in entry, "WIN5_TWO_METADATA_CARDS_LAYOUT_MISSING")

    require("tech.setAttribute('open', '')" in entry, "WIN5_DIAGNOSTICS_NOT_FORCED_OPEN")
    require("summary.replaceWith(staticTitle)" in entry, "WIN5_DIAGNOSTICS_STILL_COLLAPSIBLE")
    require("各レースの1着確率・学習情報" in entry, "WIN5_STATIC_DIAGNOSTICS_TITLE_MISSING")
    require("otherPanel.append(diagnosticsSection)" in entry, "WIN5_DIAGNOSTICS_NOT_MOVED_TO_OTHER")
    require("otherPanel.append(quick)" in entry, "WIN5_METADATA_NOT_MOVED_TO_OTHER")

    require("各レースの1着予想と、最近の結果の反映状況" in canonical, "WIN5_CLEAR_DIAGNOSTICS_LABEL_MISSING")
    require("5レースすべて的中" in canonical, "WIN5_CLEAR_HIT_PROBABILITY_LABEL_MISSING")
    require("最初の対象レースの発走15分前" in canonical, "WIN5_CLEAR_DEADLINE_LABEL_MISSING")

    require('if (validSnapshot(existing, snapshot.date) && existing.locked) return existing;' in runtime, "WIN5_FINAL_IMMUTABILITY_GUARD_MISSING")
    require('nowMs >= cachedDeadlineMs && nowMs < cachedFirstStartMs' in runtime, "WIN5_STORED_PREVIEW_DEADLINE_GUARD_MISSING")
    require('await lockSnapshot(env.DB, preview, now, "last_good")' in runtime, "WIN5_PREVIEW_PROMOTION_MISSING")
    require('const freshCache = await resolveWin5Targets(env.DB, date, now, true)' not in runtime, "WIN5_POST_DEADLINE_FRESH_REGEN_REINTRODUCED")
    require('if (nowMs < deadlineMs)' in runtime, "WIN5_PREVIEW_NOT_CUTOFF_AT_DEADLINE")
    require('WIN5_DEADLINE_GUARD_BEFORE' in deadline and 'WIN5_DEADLINE_GUARD_AFTER' in deadline, "WIN5_INDEPENDENT_DEADLINE_GUARD_MISSING")
    require('state.status === "final" && state.snapshot?.lockedAt' in parent, "WIN5_UI_NOT_SHOWING_ACTUAL_LOCK_TIME")
    require('detail: "T-15で固定済み"' not in parent, "WIN5_UI_FALSE_T15_CLAIM_REINTRODUCED")

    require('.win5-target-list' in parent and '.win5-ticket-row' in parent, "WIN5_MOBILE_VERTICAL_LAYOUT_MISSING")
    require('overflow-x:auto' not in source, "WIN5_HORIZONTAL_SCROLL_REINTRODUCED")

    print("WIN5_UI_OK top_nav=true floating_button=false view_switch=tickets_other default=tickets duplicate_plan_comparison=false rule=false diagnostics=always_open horizontal_scroll=false canonical=v30 clear_language=true")


if __name__ == "__main__":
    main()
