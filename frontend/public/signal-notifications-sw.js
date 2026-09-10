// This worker displays notifications from the app's existing polling feed.
// It deliberately has no fetch handler or application caching.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const signalId = event.notification.data?.signalId;
  if (typeof signalId !== "string" || !signalId) return;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const tab = windows.find((client) => {
      const url = new URL(client.url);
      return url.origin === self.location.origin && (url.pathname === "/" || url.pathname.startsWith("/runs/"));
    });
    if (tab) {
      tab.postMessage({ type: "catchcatch:open-signal", signalId });
      await tab.focus();
    } else {
      await self.clients.openWindow(`/?signal=${encodeURIComponent(signalId)}`);
    }
  })());
});
