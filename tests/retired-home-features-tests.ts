import {strict as assert} from "node:assert";
import {NORMAL_HOME_SNAPSHOT} from "../src/normal-home-snapshot.js";
import {RETIRED_PUBLIC_PATH_RE,removeRetiredLinks,removeUnusedHomeSections}
  from "../src/v1/retired-public-features-ui.js";

const original=NORMAL_HOME_SNAPSHOT;
for(const phrase of [
  "開催日を選んで予想・結果を確認できます。",
  "予想・買い目は各レース詳細で確認",
  "WIN5",
  "累計回収率",
  "会場別回収率",
  "本日の集計",
]){
  assert.ok(original.includes(phrase),"source snapshot missing "+phrase);
}
const cleaned=removeUnusedHomeSections(original);
for(const phrase of [
  "開催日を選んで予想・結果を確認できます。",
  "予想・買い目は各レース詳細で確認",
  "home-hero-compact\"><h1>レース",
  'home-live-learning home-guide-compact" aria-label="予想案内"',
  'href="/win5"',
  'href="/adhoc"',
  "WIN5",
]){
  assert.ok(!cleaned.includes(phrase),"unused UI still rendered: "+phrase);
}
for(const phrase of [
  "累計回収率",
  "会場別回収率",
  "本日の集計",
  'id="races"',
  'id="years"',
  'id="months"',
  'href="/conditions"',
  "予想のしくみ",
]){
  assert.ok(cleaned.includes(phrase),"existing canonical content removed: "+phrase);
}
assert.equal(removeUnusedHomeSections(cleaned),cleaned,"final cleanup must be idempotent");
const fallback='<header><nav class="nav"><a href="/adhoc">指定予想</a><a href="/win5">WIN5</a><a href="/conditions">条件詳細</a></nav></header>';
const filtered=removeRetiredLinks(fallback);
assert.ok(!filtered.includes("WIN5")&&!filtered.includes("指定予想"));
assert.ok(filtered.includes('href="/conditions"'));
for(const path of [
  "/adhoc","/adhoc/","/api/adhoc/races","/api/adhoc/request","/api/adhoc/status",
  "/win5","/win5/","/api/win5/status","/api/public/win5"
])assert.ok(RETIRED_PUBLIC_PATH_RE.test(path),"retired route not blocked "+path);
for(const path of [
  "/","/races","/races/2026-11-15-tokyo-01","/conditions",
  "/guide","/api/public/daily-performance","/api/public/cumulative-performance"
])assert.ok(!RETIRED_PUBLIC_PATH_RE.test(path),"canonical route accidentally blocked "+path);
console.log("RETIRED_HOME_ADHOC_WIN5_NO_CANONICAL_DATA_CHANGE_TEST_OK");
