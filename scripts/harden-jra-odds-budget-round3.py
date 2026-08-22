from pathlib import Path

fast_path = Path("src/v1/jra-official-odds-fetch.ts")
fast = fast_path.read_text()

old = 'const PAGE_TIMEOUT_MS = 4_500;\nconst PAGE_ATTEMPTS = 3;'
new = 'const PAGE_TIMEOUT_MS = 4_500;\nconst PAGE_ATTEMPTS = 3;\nconst FETCH_BUDGET_MS = 25_000;'
assert old in fast, "fast odds constants changed unexpectedly"
fast = fast.replace(old, new, 1)

old = 'class JraFetchSession {\n  private cookies = new Map<string, string>();'
new = 'class JraFetchSession {\n  private cookies = new Map<string, string>();\n\n  constructor(private readonly deadlineMs: number) {}'
assert old in fast, "JraFetchSession declaration changed unexpectedly"
fast = fast.replace(old, new, 1)

old = '''    for (let attempt = 0; attempt < PAGE_ATTEMPTS; attempt += 1) {
      const headers = new Headers({'''
new = '''    for (let attempt = 0; attempt < PAGE_ATTEMPTS; attempt += 1) {
      const remainingBudgetMs = this.deadlineMs - Date.now();
      if (remainingBudgetMs <= 0) throw new Error("JRA_ODDS_FETCH_BUDGET_EXHAUSTED");
      const headers = new Headers({'''
assert old in fast, "session attempt loop changed unexpectedly"
fast = fast.replace(old, new, 1)

old = '      const timer = setTimeout(() => controller.abort(), PAGE_TIMEOUT_MS);'
new = '      const timer = setTimeout(() => controller.abort(), Math.max(1, Math.min(PAGE_TIMEOUT_MS, remainingBudgetMs)));'
assert old in fast, "session timeout line changed unexpectedly"
fast = fast.replace(old, new, 1)

old = 'async function fetchFastDirect(entryUrl: string, target: JraOddsIdentity): Promise<FastJraOddsResult> {\n  const session = new JraFetchSession();'
new = 'async function fetchFastDirect(entryUrl: string, target: JraOddsIdentity, deadlineMs: number): Promise<FastJraOddsResult> {\n  const session = new JraFetchSession(deadlineMs);'
assert old in fast, "fetchFastDirect signature changed unexpectedly"
fast = fast.replace(old, new, 1)

old = 'async function fetchOfficialCrawlFallback(entryUrl: string, target: JraOddsIdentity, fastError: unknown): Promise<FastJraOddsResult> {\n  const crawl = await crawlJraOfficialOddsForRace(entryUrl, target);'
new = 'async function fetchOfficialCrawlFallback(entryUrl: string, target: JraOddsIdentity, fastError: unknown, deadlineMs: number): Promise<FastJraOddsResult> {\n  const crawl = await crawlJraOfficialOddsForRace(entryUrl, target, deadlineMs);'
assert old in fast, "crawl fallback signature changed unexpectedly"
fast = fast.replace(old, new, 1)

old = '''  const attemptedHosts: string[] = [];
  const fastErrors: string[] = [];

  for (const candidate of candidates) {'''
new = '''  const attemptedHosts: string[] = [];
  const fastErrors: string[] = [];
  const deadlineMs = Date.now() + FETCH_BUDGET_MS;

  for (const candidate of candidates) {
    if (Date.now() >= deadlineMs) {
      fastErrors.push("budget:JRA_ODDS_FETCH_BUDGET_EXHAUSTED");
      break;
    }'''
assert old in fast, "top-level fast loop changed unexpectedly"
fast = fast.replace(old, new, 1)

old = '      const result = await fetchFastDirect(candidate, target);'
new = '      const result = await fetchFastDirect(candidate, target, deadlineMs);'
assert old in fast, "fast direct invocation changed unexpectedly"
fast = fast.replace(old, new, 1)

old = '''  const aggregateFastError = new Error(`JRA_ODDS_FAST_ALL_HOSTS_FAILED:${fastErrors.join("|")}`);
  try {
    const crawl = await fetchOfficialCrawlFallback(entryUrl, target, aggregateFastError);'''
new = '''  const aggregateFastError = new Error(`JRA_ODDS_FAST_ALL_HOSTS_FAILED:${fastErrors.join("|")}`);
  if (Date.now() >= deadlineMs) throw new Error(`JRA_ODDS_ALL_PATHS_BUDGET_EXHAUSTED:fast=${fastErrors.join("|")}`);
  try {
    const crawl = await fetchOfficialCrawlFallback(entryUrl, target, aggregateFastError, deadlineMs);'''
assert old in fast, "crawl invocation block changed unexpectedly"
fast = fast.replace(old, new, 1)
fast_path.write_text(fast)

crawl_path = Path("src/v1/jra-official-odds.ts")
crawl = crawl_path.read_text()
old = 'const VENUES = "札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉";'
new = 'const VENUES = "札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉";\nconst CRAWL_PAGE_TIMEOUT_MS = 3_500;'
assert old in crawl, "crawl constants changed unexpectedly"
crawl = crawl.replace(old, new, 1)

old = 'async function fetchHtml(url: string, cname?: string, referer = "https://www.jra.go.jp/"): Promise<string> {'
new = 'async function fetchHtml(url: string, cname?: string, referer = "https://www.jra.go.jp/", deadlineMs = Number.POSITIVE_INFINITY): Promise<string> {'
assert old in crawl, "fetchHtml signature changed unexpectedly"
crawl = crawl.replace(old, new, 1)

old = '''  if (cname != null) { body = new URLSearchParams({ cname }).toString(); headers["Content-Type"] = "application/x-www-form-urlencoded"; }
  const response = await fetch(url, { method: body ? "POST" : "GET", headers, body, redirect: "follow" });
  if (!response.ok) throw new Error(`JRA_ODDS_HTTP_${response.status}`);'''
new = '''  if (cname != null) { body = new URLSearchParams({ cname }).toString(); headers["Content-Type"] = "application/x-www-form-urlencoded"; }
  const remainingBudgetMs = deadlineMs - Date.now();
  if (remainingBudgetMs <= 0) throw new Error("JRA_ODDS_CRAWL_BUDGET_EXHAUSTED");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.max(1, Math.min(CRAWL_PAGE_TIMEOUT_MS, remainingBudgetMs)));
  let response: Response;
  try {
    response = await fetch(url, { method: body ? "POST" : "GET", headers, body, redirect: "follow", signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) throw new Error(`JRA_ODDS_HTTP_${response.status}`);'''
assert old in crawl, "fetchHtml fetch block changed unexpectedly"
crawl = crawl.replace(old, new, 1)

old = 'export async function crawlJraOfficialOddsForRace(entryUrl: string, target: JraOddsIdentity): Promise<JraOfficialOddsCrawlResult> {\n  const entryHtml = await fetchHtml(entryUrl);'
new = 'export async function crawlJraOfficialOddsForRace(entryUrl: string, target: JraOddsIdentity, deadlineMs = Number.POSITIVE_INFINITY): Promise<JraOfficialOddsCrawlResult> {\n  const entryHtml = await fetchHtml(entryUrl, undefined, "https://www.jra.go.jp/", deadlineMs);'
assert old in crawl, "crawl signature changed unexpectedly"
crawl = crawl.replace(old, new, 1)

old = '  while (queue.length && seen.size < 40) {'
new = '  while (queue.length && seen.size < 40 && Date.now() < deadlineMs) {'
assert old in crawl, "crawl loop changed unexpectedly"
crawl = crawl.replace(old, new, 1)

old = '      const page = await fetchHtml(JRA_ODDS_URL, cname, JRA_ODDS_URL);'
new = '      const page = await fetchHtml(JRA_ODDS_URL, cname, JRA_ODDS_URL, deadlineMs);'
assert old in crawl, "crawl page fetch changed unexpectedly"
crawl = crawl.replace(old, new, 1)
crawl_path.write_text(crawl)

print("round3 JRA odds budget hardening applied")
