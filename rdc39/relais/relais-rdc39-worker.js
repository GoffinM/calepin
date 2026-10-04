/**
 * Relais RDC39-Calepin (Cloudflare Worker)
 * ---------------------------------------------------------------------------
 * Rôle limité à deux choses (aucune IA, aucune clé API) :
 *   1. valider le code d'accès de l'équipe (révocable à tout moment) ;
 *   2. recevoir les relevés et les ranger dans Cloudflare KV.
 * Plus une petite interface d'administration (page rdc39/admin.html), protégée
 * par un code distinct, pour lister et télécharger les visites.
 *
 * Routes (toutes en POST) :
 *   /validate-code     {code}                   -> 200 {ok, graceDays} | 403
 *   /upload-entry      {visitUid, entry}        -> KV "e:<visitUid>:<entryId>"   (code équipe)
 *   /upload-manifest   manifeste de la visite   -> KV "m:<visitUid>"             (code équipe)
 *   /admin/list        {}                       -> liste des visites             (code admin)
 *   /admin/visit       {uid}                    -> digest complet réassemblé     (code admin)
 * En GET (ouvrir l'URL dans un navigateur) : page de diagnostic, sans aucun secret.
 *
 * Une visite est envoyée en morceaux : un objet KV par entrée (photo, audio, note...)
 * puis un manifeste (métadonnées + liste des entrées). Un envoi coupé sur réseau
 * faible ne fait perdre que l'entrée en cours, reprise au prochain essai.
 *
 * ---------------------------------------------------------------------------
 * Variables du Worker (Settings -> Variables and Secrets) :
 *   ACCESS_CODES    (Secret)  codes de l'équipe, séparés par des virgules.
 *                             RÉVOQUER = retirer le code de la liste (effet dès que
 *                             l'appareil se reconnecte, sans redéployer l'app).
 *   ADMIN_CODE      (Secret)  code de la page d'administration (différent des codes
 *                             d'équipe : l'équipe ne peut pas lire les relevés des autres).
 *   GRACE_DAYS      (Texte)   délai de grâce hors-ligne en jours (défaut 14).
 *   ALLOWED_ORIGIN  (Texte)   facultatif — ex. "https://goffinm.github.io".
 * Liaison KV (Settings -> Bindings -> KV namespace) : variable DIGESTS.
 * Les anciennes clés IA (ANTHROPIC_API_KEY...) ne servent plus : supprimez-les.
 *
 * Limites du palier gratuit KV (vérifiées le 04/10/2026) : 1 000 écritures/jour,
 * 1 000 listes/jour, 100 000 lectures/jour, 25 Mio par valeur, 1 Go de stockage.
 * Chaque entrée = 1 écriture, chaque manifeste = 1 écriture.
 * ---------------------------------------------------------------------------
 */

const MAX_VALUE_BYTES = 24 * 1024 * 1024; // marge sous la limite KV de 25 Mio

function corsHeaders(env){
  // Défensif : une valeur mal saisie (espace, retour à la ligne) ferait planter le Worker.
  const origin = String((env && env.ALLOWED_ORIGIN) || "*").trim().replace(/\/+$/, "") || "*";
  return {
    "Access-Control-Allow-Origin": /^[\x21-\x7e]+$/.test(origin) ? origin : "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "X-Access-Code, X-Admin-Code, X-Device-Id, Content-Type",
    "Access-Control-Max-Age": "86400"
  };
}
function json(env, status, obj){
  return new Response(JSON.stringify(obj), {
    status,
    headers: Object.assign({ "Content-Type": "application/json" }, corsHeaders(env))
  });
}
function codeList(value){
  return String(value || "").split(",").map(s => s.trim()).filter(Boolean);
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
function matchesAny(list, code){
  if(!code) return false;
  let ok = false;
  for(const c of list) if(safeEqual(c, code)) ok = true;
  return ok;
}
function safeId(s){ return String(s || "").replace(/[^A-Za-z0-9_-]/g, "").slice(0, 80); }

export default {
  async fetch(request, env) {
    // Toute erreur inattendue est renvoyée en clair (jamais de secret dedans), plutôt que
    // la page générique "Error 1101" de Cloudflare.
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
      "Codes équipe : " + (codeList(env.ACCESS_CODES).length ? "oui" : "NON (ACCESS_CODES manquant)") + ". " +
      "Stockage KV : " + (env.DIGESTS ? "lié" : "NON lié (binding DIGESTS manquant)") + ". " +
      "Code admin : " + (env.ADMIN_CODE ? "oui" : "NON (ADMIN_CODE manquant, page d'administration inactive)") + ".";
    return new Response(diag, { status: 200, headers: Object.assign({ "Content-Type": "text/plain; charset=utf-8" }, corsHeaders(env)) });
  }
  const url = new URL(request.url);

  // --- Validation du code d'accès ---
  if (url.pathname === "/validate-code") {
    let body = {};
    try { body = await request.json(); } catch (e) {}
    if (!matchesAny(codeList(env.ACCESS_CODES), String(body.code || "").trim())) return json(env, 403, { ok: false });
    return json(env, 200, { ok: true, graceDays: Number(env.GRACE_DAYS) || 14 });
  }

  if (!env.DIGESTS) return json(env, 500, { ok: false, error: "Espace KV DIGESTS non lié au Worker." });

  // --- Administration (code distinct) ---
  if (url.pathname.startsWith("/admin/")) {
    const adminCode = (request.headers.get("X-Admin-Code") || "").trim();
    if (!env.ADMIN_CODE || !matchesAny([String(env.ADMIN_CODE).trim()], adminCode)) return json(env, 403, { ok: false, error: "code admin" });
    if (url.pathname === "/admin/list") {
      const visits = [];
      let cursor;
      do {
        const page = await env.DIGESTS.list({ prefix: "m:", cursor });
        page.keys.forEach(k => visits.push(Object.assign({ uid: k.name.slice(2) }, k.metadata || {})));
        cursor = page.list_complete ? null : page.cursor;
      } while (cursor);
      return json(env, 200, { ok: true, visits });
    }
    if (url.pathname === "/admin/visit") {
      let body = {};
      try { body = await request.json(); } catch (e) {}
      const uid = safeId(body.uid);
      if (!uid) return json(env, 400, { ok: false, error: "uid manquant." });
      const manifest = await env.DIGESTS.get("m:" + uid, "json");
      if (!manifest) return json(env, 404, { ok: false, error: "Visite inconnue." });
      const stored = {};
      let cursor;
      do {
        const page = await env.DIGESTS.list({ prefix: "e:" + uid + ":", cursor });
        for (const k of page.keys) stored[k.name.slice(("e:" + uid + ":").length)] = k.name;
        cursor = page.list_complete ? null : page.cursor;
      } while (cursor);
      const entries = [], manquantes = [];
      const listed = (manifest.entrees || []).map(e => e.id);
      for (const id of listed) {
        if (!stored[id]) { manquantes.push(id); continue; }
        const e = await env.DIGESTS.get(stored[id], "json");
        if (e) entries.push(e); else manquantes.push(id);
      }
      // Entrées reçues mais supprimées depuis sur le téléphone : conservées, signalées.
      for (const id of Object.keys(stored)) {
        if (listed.includes(id)) continue;
        const e = await env.DIGESTS.get(stored[id], "json");
        if (e) entries.push(Object.assign(e, { supprimeeSurTelephone: true }));
      }
      const digest = Object.assign({}, manifest, { entries, entreesManquantes: manquantes });
      delete digest.entrees;
      return json(env, 200, digest);
    }
    return json(env, 404, { ok: false, error: "Route inconnue." });
  }

  // --- Toutes les autres routes : code d'équipe obligatoire ---
  const code = (request.headers.get("X-Access-Code") || "").trim();
  if (!matchesAny(codeList(env.ACCESS_CODES), code)) return json(env, 403, { ok: false, error: "code" });
  const device = (request.headers.get("X-Device-Id") || "").slice(0, 64);
  const receivedAt = new Date().toISOString();

  if (url.pathname === "/upload-entry" || url.pathname === "/upload-manifest") {
    const text = await request.text();
    if (text.length > MAX_VALUE_BYTES) return json(env, 413, { ok: false, error: "Trop volumineux (" + Math.round(text.length / 1048576) + " Mo)." });
    let body;
    try { body = JSON.parse(text); } catch (e) { return json(env, 400, { ok: false, error: "JSON invalide." }); }

    if (url.pathname === "/upload-entry") {
      const visitUid = safeId(body.visitUid);
      const entry = body.entry || {};
      const entryId = safeId(entry.id);
      if (!visitUid || !entryId) return json(env, 400, { ok: false, error: "visitUid ou entry.id manquant." });
      const value = JSON.stringify(entry);
      await env.DIGESTS.put("e:" + visitUid + ":" + entryId, value, {
        metadata: { type: entry.type || null, horodatage: entry.horodatage || null, taille: value.length, appareil: device, recuLe: receivedAt }
      });
      return json(env, 200, { ok: true, receivedAt });
    }

    const uid = safeId(body.uid);
    if (!uid) return json(env, 400, { ok: false, error: "uid manquant." });
    await env.DIGESTS.put("m:" + uid, text, {
      metadata: {
        repere: String(body.tag || "").slice(0, 120),
        date: body.date || null,
        dossier: body.dossier ? String(body.dossier).slice(0, 120) : null,
        appareil: device || body.appareil || null,
        recuLe: receivedAt,
        entrees: Array.isArray(body.entrees) ? body.entrees.length : 0,
        corbeille: !!body.corbeille
      }
    });
    return json(env, 200, { ok: true, receivedAt });
  }

  return json(env, 404, { ok: false, error: "Route inconnue." });
}
