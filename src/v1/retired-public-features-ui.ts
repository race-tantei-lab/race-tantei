/**
 * Presentation-only cleanup of retired features.
 * Applied at the final public Worker boundary, after any embedded HTML
 * snapshot or fallback has rendered, so it cannot silently reintroduce links.
 * Does not change canonical race selection, payouts, or historical records.
 */
export const RETIRED_PUBLIC_PATH_RE =
  /^\/(?:adhoc(?:\/|$)|win5(?:\/|$)|api\/(?:adhoc|win5)(?:\/|$)|api\/public\/win5(?:\/|$))/i;

export function removeRetiredLinks(html:string):string{
  // Retire links in the main bar and any fallback/legacy page. Never strip
  // canonical /races/:id, /conditions, /guide, or performance links.
  return html.replace(/<a\b[^>]*\bhref=(["'])\/(?:adhoc|win5)(?:\/[^"']*)?\1[^>]*>[\s\S]*?<\/a>\s*/gi,"");
}

export function removeUnusedHomeSections(html:string):string{
  let out=removeRetiredLinks(html);
  // Remove exactly the two old introductory cards outlined in the screenshot.
  // The year/month/date/venue/race navigation and all performance metrics that
  // follow are never modified by these targeted class/section matches.
  out=out.replace(/<section\b[^>]*\bclass=(["'])[^"']*\bhome-hero-compact\b[^"']*\1[^>]*>[\s\S]*?<\/section>\s*/gi,"");
  out=out.replace(/<section\b[^>]*\bclass=(["'])[^"']*\bhome-guide-compact\b[^"']*\1[^>]*>[\s\S]*?<\/section>\s*/gi,"");
  // If an older cached page already contains the previously injected card,
  // make the homepage removal idempotent.
  out=out.replace(/<section\b[^>]*\bid=(["'])adhoc-home-entry\1[^>]*>[\s\S]*?<\/section>\s*/gi,"");
  return out;
}
