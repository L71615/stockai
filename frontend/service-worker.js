// StockAI Service Worker — 离线缓存 + 后台更新
const CACHE_STATIC = 'stockai-static-v2';
const CACHE_DYNAMIC = 'stockai-dynamic-v2';

const STATIC_FILES = [
  './',
  './index.html',
  './login.html',
  './watchlist.html',
  './market.html',
  './global-news.html',
  './ai-assistant.html',
  './skills.html',
  './transactions.html',
  './settings.html',
  './css/common.css',
  './js/common.js',
  './manifest.json',
  './icon.svg',
  './icon-192.png',
  './icon-512.png',
];

// Install: 预缓存静态文件
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_STATIC)
      .then(cache => cache.addAll(STATIC_FILES))
      .then(() => self.skipWaiting())
  );
});

// Activate: 清理旧版本缓存
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_STATIC && k !== CACHE_DYNAMIC)
          .map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// Fetch: 差异化缓存策略
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // 跳过非 GET 请求
  if (e.request.method !== 'GET') return;

  // 跳过 chrome-extension 等非 http 协议
  if (!url.protocol.startsWith('http')) return;

  // API 请求: 网络优先，失败时缓存兜底
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(networkFirst(e.request));
    return;
  }

  // 静态文件: 缓存优先
  e.respondWith(cacheFirst(e.request));
});

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  try {
    const res = await fetch(request);
    if (res.ok) {
      const cache = await caches.open(CACHE_DYNAMIC);
      cache.put(request, res.clone());
    }
    return res;
  } catch (err) {
    // 导航请求回退到 index.html (SPA)
    if (request.mode === 'navigate') {
      const fallback = await caches.match('./index.html');
      if (fallback) return fallback;
    }
    throw err;
  }
}

async function networkFirst(request) {
  try {
    const res = await fetch(request);
    if (res.ok) {
      const cache = await caches.open(CACHE_DYNAMIC);
      cache.put(request, res.clone());
    }
    return res;
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw err;
  }
}
