// RDC39-Calepin — service worker
// Même stratégie que Calepin pour l'app ("réseau d'abord, cache en secours"), plus :
//  - couches GeoJSON du projet et Leaflet mis en cache dès l'installation (carte hors-ligne) ;
//  - tuiles OpenStreetMap servies depuis leur propre cache (rempli par le bouton
//    "Télécharger pour le terrain", ou au fil de la consultation en ligne).
//
// ATTENTION — même origine que le Calepin personnel (goffinm.github.io) : les caches sont
// partagés entre les deux apps. On ne supprime donc JAMAIS que nos propres caches
// (préfixe "rdc39-shell-"), et le cache de tuiles n'est jamais vidé par une mise à jour.
const CACHE_PREFIX = 'rdc39-shell-';
const CACHE_NAME = CACHE_PREFIX + '2026-10-05-4'; // à incrémenter AVEC APP_VERSION (index.html) à chaque livraison
const TILE_CACHE = 'rdc39-tiles-v1';
const NETWORK_TIMEOUT_MS = 3000;
const LEAFLET_FILES = [
  'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css',
  'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js'
];
const SHELL_FILES = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.svg',
  './icon-512.svg',
  './layers/bvbig.geojson',
  './layers/bv-dam-site-1.geojson',
  './layers/bv-dam-site-2.geojson',
  './layers/bv-dam-site-3.geojson',
  './layers/max-possible-site-1.geojson',
  './layers/max-possible-site-2.geojson',
  './layers/max-possible-site-3.geojson',
  './layers/riviere.geojson',
  './layers/contours-0-5mfrom-barrage.geojson',
  './layers/points-sites.geojson',
  './layers/conduite.geojson'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => Promise.all(
        SHELL_FILES.map((url) => cache.add(new Request(url, { cache: 'reload' })))
          .concat(LEAFLET_FILES.map((url) => cache.add(new Request(url, { mode: 'cors' })).catch(() => {})))
      ))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names
          .filter((name) => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME)
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
    const cached = await cache.match(request, { ignoreSearch: request.mode === 'navigate' });
    if(cached) return cached;
    if(request.mode === 'navigate'){
      const shell = await cache.match('./index.html');
      if(shell) return shell;
    }
    throw err;
  }
}

// Leaflet (CDN, version figée) : cache d'abord.
async function cacheFirst(request){
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request.url);
  if(cached) return cached;
  const response = await fetch(new Request(request.url, { mode: 'cors' }));
  if(response && response.ok) cache.put(request.url, response.clone());
  return response;
}

// Tuiles OSM : cache d'abord ; en cas d'absence, réseau (requête CORS, pas "opaque",
// pour ne pas gonfler artificiellement le quota) puis mise en cache.
async function tileFirst(request){
  const cache = await caches.open(TILE_CACHE);
  const cached = await cache.match(request.url);
  if(cached) return cached;
  try{
    const response = await fetch(new Request(request.url, { mode: 'cors' }));
    if(response && response.ok) cache.put(request.url, response.clone());
    return response;
  }catch(err){
    return new Response('', { status: 504, statusText: 'Tuile hors-ligne' });
  }
}

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.hostname === 'tile.openstreetmap.org'){ event.respondWith(tileFirst(event.request)); return; }
  if (LEAFLET_FILES.includes(url.href)){ event.respondWith(cacheFirst(event.request)); return; }
  if (url.origin !== self.location.origin) return; // relais, etc. : laissé au navigateur
  event.respondWith(networkFirst(event.request));
});
