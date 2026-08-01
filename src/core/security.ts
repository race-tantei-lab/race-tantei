const ALLOWED_HOSTS = new Set(["www.jra.go.jp", "jra.go.jp", "sp.jra.jp"]);

export function validateJraUrl(rawUrl: string): URL {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new Error("INVALID_URL");
  }

  if (url.protocol !== "https:") throw new Error("HTTPS_REQUIRED");
  if (!ALLOWED_HOSTS.has(url.hostname)) throw new Error("HOST_NOT_ALLOWED");
  if (url.username || url.password) throw new Error("CREDENTIALS_NOT_ALLOWED");
  if (url.port && url.port !== "443") throw new Error("PORT_NOT_ALLOWED");
  return url;
}
