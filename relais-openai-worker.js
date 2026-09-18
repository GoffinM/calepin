/**
 * Relais Calepin -> OpenAI / Anthropic / OpenRouter
 * --------------------------------------------------
 * Ne fait qu'une chose : transmettre la requête du navigateur vers le fournisseur
 * choisi, puis renvoyer la réponse avec les en-têtes CORS que ces fournisseurs
 * n'ajoutent pas eux-mêmes pour les appels directs depuis un navigateur.
 *
 * Ne stocke JAMAIS aucune clé API : elle transite telle qu'envoyée par Calepin
 * (en-tête Authorization pour OpenAI/OpenRouter, x-api-key pour Anthropic),
 * sans être journalisée ni conservée.
 *
 * Déploiement (gratuit, ~5 minutes) :
 * 1. https://dash.cloudflare.com -> Workers & Pages -> Create -> "Start with Hello World!"
 * 2. Donne-lui un nom (ex. "calepin-relais")
 * 3. Colle ce code entier dans l'éditeur, remplace le contenu par défaut
 * 4. Deploy
 * 5. Copie l'URL du Worker (https://calepin-relais.<ton-compte>.workers.dev)
 * 6. Colle cette URL dans Calepin -> Réglages -> URL du relais
 *
 * Si tu avais déjà déployé une version précédente de ce fichier (OpenAI seul),
 * remplace tout le contenu de ton Worker existant par celui-ci et redéploie —
 * même URL, pas besoin de recréer le Worker ni de recoller l'URL dans Calepin.
 */

const ROUTES = {
  "/transcribe":     { target: "https://api.openai.com/v1/audio/transcriptions", authHeader: "Authorization" },
  "/chat":           { target: "https://api.openai.com/v1/chat/completions",     authHeader: "Authorization" },
  "/anthropic-chat": { target: "https://api.anthropic.com/v1/messages",          authHeader: "x-api-key" },
  "/openrouter-chat":{ target: "https://openrouter.ai/api/v1/chat/completions",  authHeader: "Authorization" }
};

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization, x-api-key, anthropic-version, Content-Type"
};

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS_HEADERS });
    }

    const url = new URL(request.url);
    const route = ROUTES[url.pathname];
    if (!route) {
      return new Response("Route inconnue. Utilisez /transcribe, /chat, /anthropic-chat ou /openrouter-chat.", {
        status: 404,
        headers: CORS_HEADERS
      });
    }
    if (request.method !== "POST") {
      return new Response("Méthode non supportée.", { status: 405, headers: CORS_HEADERS });
    }

    const upstreamHeaders = new Headers();
    const authValue = request.headers.get(route.authHeader);
    if (authValue) upstreamHeaders.set(route.authHeader, authValue);
    const contentType = request.headers.get("Content-Type");
    if (contentType) upstreamHeaders.set("Content-Type", contentType);
    // Anthropic exige cet en-tête de version en plus de la clé.
    if (url.pathname === "/anthropic-chat") {
      const anthropicVersion = request.headers.get("anthropic-version") || "2023-06-01";
      upstreamHeaders.set("anthropic-version", anthropicVersion);
    }

    let upstreamResponse;
    try {
      upstreamResponse = await fetch(route.target, {
        method: "POST",
        headers: upstreamHeaders,
        body: request.body
      });
    } catch (err) {
      return new Response("Erreur relais : " + err.message, { status: 502, headers: CORS_HEADERS });
    }

    const responseHeaders = new Headers(upstreamResponse.headers);
    Object.entries(CORS_HEADERS).forEach(([k, v]) => responseHeaders.set(k, v));

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      headers: responseHeaders
    });
  }
};
