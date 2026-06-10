/**
 * PrintShelf fetch proxy — bypasses Railway IP blocks on sites like Makerworld.
 * Deploy to Cloudflare Workers. Requires PROXY_SECRET env var (Workers secret).
 *
 * Usage: GET /?url=https://makerworld.com/...&token=<PROXY_SECRET>
 */

const BROWSER_HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
  Accept:
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
  "Accept-Language": "en-US,en;q=0.9",
  "Sec-Fetch-Dest": "document",
  "Sec-Fetch-Mode": "navigate",
  "Sec-Fetch-Site": "none",
  "Upgrade-Insecure-Requests": "1",
  "Cache-Control": "no-cache",
};

export default {
  async fetch(request, env) {
    const { searchParams } = new URL(request.url);
    const target = searchParams.get("url");
    const token = searchParams.get("token");

    if (!env.PROXY_SECRET || token !== env.PROXY_SECRET) {
      return new Response("Unauthorized", { status: 401 });
    }

    if (!target || !target.startsWith("https://")) {
      return new Response("Bad Request: url must be an https URL", { status: 400 });
    }

    let response;
    try {
      response = await fetch(target, {
        headers: BROWSER_HEADERS,
        redirect: "follow",
      });
    } catch (err) {
      return new Response(`Fetch failed: ${err.message}`, { status: 502 });
    }

    const html = await response.text();
    return new Response(html, {
      status: response.status,
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "X-Proxied-Url": response.url,
        "X-Proxied-Status": String(response.status),
      },
    });
  },
};
