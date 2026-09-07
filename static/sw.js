const CACHE="routeops-v0314-shell-v1";
const SHELL=[
  "/static/style.css",
  "/static/app.js",
  "/static/smart_vision.js",
  "/static/smart_label_scanner.js",
  "/manifest.webmanifest"
];
self.addEventListener("install",event=>{
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)));
});
self.addEventListener("activate",event=>{
  event.waitUntil(Promise.all([
    caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))),
    self.clients.claim()
  ]));
});
self.addEventListener("fetch",event=>{
  if(event.request.method!=="GET") return;
  event.respondWith(fetch(event.request).catch(()=>caches.match(event.request)));
});
