export function safeRaceName(raceName: string | null | undefined, raceNo: number, conditions?: string | null): string {
  const raw = (raceName ?? "").replace(/\s+/g, " ").trim();
  const invalid = !raw
    || /^\d{1,2}(?:R|レース)$/i.test(raw)
    || /検索ウィンドウ|検索メニュー|サイト内検索|JRAホーム|メニューを開く|レース情報トップ|出馬表|オッズ|払戻|レース結果/.test(raw);
  if (!invalid) return raw;
  const cond = (conditions ?? "").replace(/\s+/g, " ").trim();
  const named = cond.match(/^(.+?)(?=(?:障害)?(?:2歳|3歳|4歳|3歳以上|4歳以上)\s*(?:未勝利|新馬|1勝クラス|2勝クラス|3勝クラス|オープン))/)?.[1]?.trim();
  if (named && named.length <= 40) return named;
  const classMatch = cond.match(/(?:障害)?(?:2歳|3歳|4歳|3歳以上|4歳以上)\s*(?:未勝利|新馬|1勝クラス|2勝クラス|3勝クラス|オープン)/);
  return classMatch?.[0]?.replace(/\s+/g, "") ?? `${raceNo}R`;
}

export function isInvalidRaceName(value: string | null | undefined): boolean {
  const raw = (value ?? "").replace(/\s+/g, " ").trim();
  return !raw
    || /^\d{1,2}(?:R|レース)$/i.test(raw)
    || /検索ウィンドウ|検索メニュー|サイト内検索|JRAホーム|メニューを開く|レース情報トップ|出馬表|オッズ|払戻|レース結果/.test(raw);
}
