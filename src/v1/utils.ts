export function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function decodeEntities(value: string): string {
  const named: Record<string, string> = {
    amp: "&",
    lt: "<",
    gt: ">",
    quot: '"',
    apos: "'",
    nbsp: " "
  };
  return value.replace(/&(#x?[0-9a-f]+|[a-z]+);/gi, (_match, entity: string) => {
    if (/^#x/i.test(entity)) {
      const code = Number.parseInt(entity.slice(2), 16);
      return Number.isFinite(code) ? String.fromCodePoint(code) : "";
    }
    if (entity.startsWith("#")) {
      const code = Number.parseInt(entity.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : "";
    }
    return named[entity.toLowerCase()] ?? "";
  });
}

export function stripHtml(value: string): string {
  return decodeEntities(
    value
      .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, "")
      .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, "")
      .replace(/<!--[\s\S]*?-->/g, "")
      .replace(/<\s*br\s*\/?>/gi, "\n")
      .replace(/<[^>]+>/g, " ")
  )
    .replace(/[\u00a0\t ]+/g, " ")
    .replace(/\r/g, "")
    .replace(/\n\s+/g, "\n")
    .trim();
}

export function htmlToLines(html: string): string[] {
  return stripHtml(
    html
      .replace(/<\/(?:td|th|tr|li|p|div|section|article|h[1-6]|dt|dd|ul|ol|table)>/gi, "\n")
  )
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

export function tableRows(html: string): string[][] {
  const rows: string[][] = [];
  for (const match of html.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
    const cells: string[] = [];
    for (const cell of (match[1] ?? "").matchAll(/<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi)) {
      cells.push(stripHtml(cell[1] ?? "").replace(/\n+/g, " ").trim());
    }
    if (cells.length > 0) rows.push(cells);
  }
  return rows;
}

export function positiveInt(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function positiveNumber(value: string | undefined, fallback: number): number {
  const parsed = Number.parseFloat(value ?? "");
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function round100(value: number): number {
  return Math.max(0, Math.round(value / 100) * 100);
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function nowIso(): string {
  return new Date().toISOString();
}

export function formatYen(value: number): string {
  return `${Math.round(value).toLocaleString("ja-JP")}円`;
}

export function parseJapaneseDateTime(year: number, month: number, day: number, time: string | null): string | null {
  if (!time) return null;
  const match = time.match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return null;
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  return new Date(Date.UTC(year, month - 1, day, hour - 9, minute)).toISOString();
}

export function isJstRaceWindow(date = new Date()): boolean {
  const jst = new Date(date.getTime() + 9 * 60 * 60 * 1000);
  const day = jst.getUTCDay();
  const hour = jst.getUTCHours();
  return (day === 0 || day === 6) && hour >= 8 && hour <= 20;
}

export function isJstEntryWindow(date = new Date()): boolean {
  const jst = new Date(date.getTime() + 9 * 60 * 60 * 1000);
  const day = jst.getUTCDay();
  return day >= 4 || day === 0;
}
