// Calepin — service worker
// Stratégie "réseau d'abord, cache en secours" (network-first) :
//  - en ligne : on récupère toujours la version la plus récente et on met le cache à jour
//    → une mise à jour de l'app arrive toute seule, sans réinstaller l'icône ;
//  - hors ligne ou réseau trop lent (> 3 s) : on sert la copie en cache
//    → l'app reste pleinement utilisable sur le terrain, sans réseau.
// (Ancienne stratégie "cache d'abord" abandonnée : elle figeait les testeurs sur une
//  vieille version tant que CACHE_NAME n'était pas changé à la main — et ce numéro
//  n'avait pas été incrémenté correctement.)
const CACHE_NAME = 'calepin-2026-09-28-2';
const NETWORK_TIMEOUT_MS = 3000;
const SHELL_FILES = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.svg',
  './icon-512.svg'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => Promise.all(
        // cache:'reload' contourne le cache HTTP du navigateur : on met en cache la vraie version du serveur
        SHELL_FILES.map((url) => cache.add(new Request(url, { cache: 'reload' })))
      ))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      )
    ).then(() => self.clients.claim())
  );
});

function fetchWithTimeout(request, ms){
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), ms);
    fetch(request).then(
      (response) => { clearTimeout(timer); resolve(response); },
      (error) => { clearTimeout(timer); reject(error); }
    );
  });
}

async function networkFirst(request){
  const cache = await caches.open(CACHE_NAME);
  try{
    const response = await fetchWithTimeout(request, NETWORK_TIMEOUT_MS);
    if(response && response.status === 200 && response.type === 'basic'){
      cache.put(request, response.clone());
    }
    return response;
  }catch(err){
    const cached = await cache.match(request);
    if(cached) return cached;
    if(request.mode === 'navigate'){
      const shell = await cache.match('./index.html');
      if(shell) return shell;
    }
    throw err;
  }
}

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  event.respondWith(networkFirst(event.request));
});
