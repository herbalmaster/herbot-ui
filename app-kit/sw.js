/* Herbot minimal service worker.
 * Chrome on Android only offers "Install app" if the page registers a worker with a fetch
 * handler, so this is here to satisfy that and nothing else.
 *
 * IT DELIBERATELY DOES NOT CACHE. These apps sit behind Cloudflare Access; a cache would serve
 * stale pages, or worse, a cached Access login page. Do not add caching without asking the design
 * system chat first.
 * Serve it from the app's own origin at /sw.js.
 */
self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (e) { e.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", function (e) { e.respondWith(fetch(e.request)); });
