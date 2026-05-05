self.addEventListener('install', (e) => {
  console.log('[Service Worker] Install');
});

self.addEventListener('fetch', (e) => {
  // LIS is a live socket-based app, so we bypass cache for API/WS calls
  // Basic pass-through fetch handler for now
  e.respondWith(fetch(e.request));
});
