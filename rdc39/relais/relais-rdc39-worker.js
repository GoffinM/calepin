/**
 * Relais RDC39-Calepin (Cloudflare Worker) — un seul Worker, plusieurs routes
 * ---------------------------------------------------------------------------
 * Même principe que le relais du Calepin personnel (transmission pure vers les
 * fournisseurs IA, en-têtes CORS), avec trois différences :
 *
 *  1. Les clés API sont PRÉCHARGÉES ici, comme variables secrètes du Worker — jamais
 *     envoyées au téléphone, jamais présentes dans le code public de l'app.
 *  2. TOUTES les routes exigent le code d'accès de l'équipe (en-tête X-Access-Code,
 *     ou champ "code" pour /validate-code). Une URL de relais découverte par hasard
 *     ne permet donc ni de consommer le budget IA, ni de déposer des données.
 *  3. Deux routes nouvelles : /validate-code et /upload-digest (dépôt dans Cloudflare KV).
 *
 * Routes :
 *   POST /validate-code     {code}  -> 200 {ok:true, graceDays} | 403
 *   POST /chat              (OpenAI chat completions)      clé : OPENAI_API_KEY
 *   POST /anthropic-chat    (Anthropic messages)           clé : ANTHROPIC_API_KEY
 *   POST /openrouter-chat   (OpenRouter chat completions)  clé : OPENROUTER_API_KEY
 *   POST /transcribe        (OpenAI Whisper — repris tel quel, inutilisé par l'app actuelle)
 *   POST /upload-digest     digest JSON d'une visite -> KV, clé "visite:<uid>"
 *
 * ---------------------------------------------------------------------------
 * Variables du Worker (Settings -> Variables and Secrets) :
 *   ACCESS_CODES        (Secret)  codes valides, séparés par des virgules.
 *                                 Ex. "terrain-2026, lea-xyz". Pour RÉVOQUER : retirer
 *                                 le code de la liste (ou la vider) -> effet immédiat
 *                                 dès que l'appareil se reconnecte, sans redéployer l'app.
 *                                 Astuce : un code par personne permet de révoquer
 *                                 quelqu'un sans toucher aux autres.
 *   GRACE_DAYS          (Texte)   délai de grâce hors-ligne en jours (défaut 14).
 *   ANTHROPIC_API_KEY   (Secret)  facultatif — au moins une des trois clés IA.
 *   OPENAI_API_KEY      (Secret)  facultatif
 *   OPENROUTER_API_KEY  (Secret)  facultatif
 *   ALLOWED_ORIGIN      (Texte)   facultatif — ex. "https://goffinm.github.io" pour
 *                                 refuser les appels venant d'autres sites (défaut : *).
 *
 * Liaison KV (Settings -> Bindings -> KV namespace) :
 *   nom de variable : DIGESTS   -> espace KV (ex. "rdc39-digests")
 *
 * Récupération des données : tableau de bord Cloudflare -> Storage & Databases ->
 * KV -> rdc39-digests -> une entrée par visite (clé "visite:<uid>", valeur = digest
 * JSON complet, photos en base64). Chaque envoi écrase la version précédente de la
 * même visite. Les métadonnées (repère, date, appareil, taille) s'affichent sans
 * ouvrir la valeur.
 *
 * Limites du palier gratuit à garder en tête : 1 000 écritures KV / jour (l'app
 * regroupe les envois, ~1 écriture par visite modifiée toutes les 2 min au plus),
 * 25 Mo max par valeur (une visite avec beaucoup de photos "Détaillée" peut
 * approcher : le relais renvoie alors 413 et l'app réessaiera — à surveiller).
 * ---------------------------------------------------------------------------
 */

const AI_ROUTES = {
  "/transcribe":      { target: "https://api.openai.com/v1/audio/transcriptions", keyVar: "OPENAI_API_KEY",     header: "Authorization", bearer: true },
  "/chat":            { target: "https://api.openai.com/v1/chat/completions",     keyVar: "OPENAI_API_KEY",     header: "Authorization", bearer: true },
  "/anthropic-chat":  { target: "https://api.anthropic.com/v1/messages",          keyVar: "ANTHROPIC_API_KEY",  header: "x-api-key",     bearer: false },
  "/openrouter-chat": { target: "https://openrouter.ai/api/v1/chat/completions",  keyVar: "OPENROUTER_API_KEY", header: "Authorization", bearer: true }
};
const MAX_DIGEST_BYTES = 24 * 1024 * 1024; // marge sous la limite KV de 25 Mio

function corsHeaders(env){
  // Défensif : une valeur mal saisie (espace, retour à la ligne) ferait planter le Worker.
  const origin = String((env && env.ALLOWED_ORIGIN) || "*").trim().replace(/\/+$/, "") || "*";
  return {
    "Access-Control-Allow-Origin": /^[\x21-\x7e]+$/.test(origin) ? origin : "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "X-Access-Code, X-Device-Id, anthropic-version, Content-Type",
    "Access-Control-Max-Age": "86400"
  };
}
function json(env, status, obj){
  return new Response(JSON.stringify(obj), {
    status,
    headers: Object.assign({ "Content-Type": "application/json" }, corsHeaders(env))
  });
}
function validCodes(env){
  return String(env.ACCESS_CODES || "").split(",").map(s => s.trim()).filter(Boolean);
}
/* Comparaison à durée constante : ne révèle pas, par le temps de réponse, combien de
   caractères d'un code sont corrects. */
function safeEqual(a, b){
  const enc = new TextEncoder();
  const x = enc.encode(a), y = enc.encode(b);
  let diff = x.length ^ y.length;
  for(let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] || 0) ^ (y[i] || 0);
  return diff === 0;
}
function isValidCode(env, code){
  if(!code) return false;
  let ok = false;
  for(const c of validCodes(env)) if(safeEqual(c, code)) ok = true;
  return ok;
}

export default {
  async fetch(request, env) {
    // Toute erreur inattendue est renvoyée en clair (sans jamais inclure de clé), plutôt que
    // la page générique "Error 1101" de Cloudflare : beaucoup plus simple à diagnostiquer.
    try {
      return await handle(request, env || {});
    } catch (err) {
      return new Response("Erreur interne du relais : " + (err && err.message ? err.message : String(err)), {
        status: 500,
        headers: { "Content-Type": "text/plain; charset=utf-8", "Access-Control-Allow-Origin": "*" }
      });
    }
  }
};

async function handle(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders(env) });
    }
    if (request.method !== "POST") {
      // Réponse visible quand on ouvre l'URL du relais dans un navigateur : sert de test.
      const diag = "Relais RDC39 actif. " +
        "Codes configurés : " + (validCodes(env).length ? "oui" : "NON (ACCESS_CODES manquant)") + ". " +
        "Stockage KV : " + (env.DIGESTS ? "lié" : "NON lié (binding DIGESTS manquant)") + ". " +
        "Clé IA : " + (env.ANTHROPIC_API_KEY || env.OPENAI_API_KEY || env.OPENROUTER_API_KEY ? "présente" : "AUCUNE") + ".";
      return new Response(diag, { status: 200, headers: Object.assign({ "Content-Type": "text/plain; charset=utf-8" }, corsHeaders(env)) });
    }
    const url = new URL(request.url);

    // --- Validation du code d'accès ---
    if (url.pathname === "/validate-code") {
      let body = {};
      try { body = await request.json(); } catch (e) {}
      const code = String(body.code || "").trim();
      if (!isValidCode(env, code)) return json(env, 403, { ok: false });
      return json(env, 200, { ok: true, graceDays: Number(env.GRACE_DAYS) || 14 });
    }

    // --- Toutes les autres routes : code d'accès obligatoire ---
    const code = (request.headers.get("X-Access-Code") || "").trim();
    if (!isValidCode(env, code)) return json(env, 403, { ok: false, error: "code" });

    // --- Dépôt d'un digest de visite dans KV ---
    if (url.pathname === "/upload-digest") {
      if (!env.DIGESTS) return json(env, 500, { ok: false, error: "Espace KV DIGESTS non lié au Worker." });
      const text = await request.text();
      if (text.length > MAX_DIGEST_BYTES) return json(env, 413, { ok: false, error: "Digest trop volumineux (" + Math.round(text.length / 1048576) + " Mo)." });
      let digest;
      try { digest = JSON.parse(text); } catch (e) { return json(env, 400, { ok: false, error: "JSON invalide." }); }
      const uid = String(digest.uid || "").replace(/[^A-Za-z0-9_-]/g, "").slice(0, 80);
      if (!uid) return json(env, 400, { ok: false, error: "uid manquant." });
      const device = (request.headers.get("X-Device-Id") || digest.appareil || "").slice(0, 64);
      const receivedAt = new Date().toISOString();
      await env.DIGESTS.put("visite:" + uid, text, {
        metadata: {
          repere: String(digest.tag || "").slice(0, 120),
          date: digest.date || null,
          appareil: device,
          recuLe: receivedAt,
          taille: text.length,
          entrees: Array.isArray(digest.entries) ? digest.entries.length : 0,
          corbeille: !!digest.corbeille
        }
      });
      return json(env, 200, { ok: true, receivedAt });
    }

    // --- Relais IA (clé ajoutée ici, jamais fournie par le téléphone) ---
    const route = AI_ROUTES[url.pathname];
    if (!route) return json(env, 404, { ok: false, error: "Route inconnue." });
    const apiKey = env[route.keyVar];
    if (!apiKey) return json(env, 503, { ok: false, error: "Clé " + route.keyVar + " non configurée sur le relais." });

    const upstreamHeaders = new Headers();
    upstreamHeaders.set(route.header, route.bearer ? "Bearer " + apiKey : apiKey);
    const contentType = request.headers.get("Content-Type");
    if (contentType) upstreamHeaders.set("Content-Type", contentType);
    if (url.pathname === "/anthropic-chat") {
      upstreamHeaders.set("anthropic-version", request.headers.get("anthropic-version") || "2023-06-01");
    }

    let upstreamResponse;
    try {
      upstreamResponse = await fetch(route.target, { method: "POST", headers: upstreamHeaders, body: request.body });
    } catch (err) {
      return new Response("Erreur relais : " + err.message, { status: 502, headers: corsHeaders(env) });
    }
    const responseHeaders = new Headers(upstreamResponse.headers);
    Object.entries(corsHeaders(env)).forEach(([k, v]) => responseHeaders.set(k, v));
    return new Response(upstreamResponse.body, { status: upstreamResponse.status, headers: responseHeaders });
}
