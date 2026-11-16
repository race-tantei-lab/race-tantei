import {strict as assert} from "node:assert";
import {NORMAL_HOME_SNAPSHOT} from "../src/normal-home-snapshot.js";
import {RETIRED_PUBLIC_PATH_RE,removeRetiredLinks,removeUnusedHomeSections}
  from "../src/v1/retired-public-features-ui.js";

const original=NORMAL_HOME_SNAPSHOT;
assert.ok(original.includes('home-hero-compact'));
assert.ok(original.includes('home-guide-compact'));
assert.ok(original.includes('href="/win5"'));
assert.ok(original.includes('id="races"'));
const clean=removeUnusedHomeSections(original);
for(const text of [
 "選定外のレースも予想できます","開催日を選んで予想・結果を確認できます。",
 "予想・買い目は各レース詳細で確認","home-live-learning home-guide-compact",
 'class="hero home-hero-compact"','href="/win5"','href="/adhoc"',
]){
 assert.ok(!clean.includes(text),"retired UI still visible: "+text);
}
for(const text of [
 'href="/"','id="races"',"累計回収率","会場別回収率","本日の集計",
 "日別回収率","予想のしくみ","使い方"
]){
 assert.ok(clean.includes(text),"canonical navigation/metrics inadvertently deleted: "+text);
}
assert.ok(clean.indexOf('累計回収率')>clean.indexOf("</header>"));
assert.equal(clean,removeUnusedHomeSections(clean),"UI cleanup is idempotent");
const edge=removeUnusedHomeSections('<main><header><nav><a href="/adhoc">指定レース予想</a><a href="/win5">WIN5</a><a href="/">レース</a></nav></header>'+
 '<section id="adhoc-home-entry"><strong>選定外のレースも予想できます</strong><a href="/adhoc">指定レースを予想する</a></section>'+
 '<div class="section-title"><h2>累計回収率</h2></div></main>');
assert.ok(!edge.includes("選定外のレース")&&!edge.includes("WIN5"));
assert.ok(edge.includes("累計回収率")&&edge.includes('href="/"'));
for(const route of ["/adhoc","/adhoc/","/api/adhoc/request","/api/adhoc/status",
 "/win5","/win5/","/api/win5","/api/win5/state","/api/public/win5/2026"]){
 assert.ok(RETIRED_PUBLIC_PATH_RE.test(route),"retired route accessible: "+route);
}
for(const route of ["/","/races","/races/2026-11-14-tokyo-01",
 "/api/public/day","/api/public/daily-performance","/performance","/conditions"]){
 assert.ok(!RETIRED_PUBLIC_PATH_RE.test(route),"canonical route blocked: "+route);
}
assert.ok(!removeRetiredLinks('<nav><a href="/win5">WIN5</a><a href="/conditions">条件詳細</a></nav>').includes("WIN5"));
console.log("CANONICAL_ONLY_RED_FRAME_ADHOC_WIN5_UI_REMOVED_OK");
