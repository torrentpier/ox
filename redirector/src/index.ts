// 301 every request from any legacy torrentpier.com subdomain
// (beta / demo / docs / faq / get) to the archive at ox.torrentpier.com,
// preserving the path and query string. URLs with no counterpart on the
// archive land on its 404 page — clearer than silently dropping the path.

export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    url.protocol = "https:";
    url.hostname = "ox.torrentpier.com";
    return Response.redirect(url.toString(), 301);
  },
} satisfies ExportedHandler;
