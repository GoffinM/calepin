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
 *   /validate-code     {code}                   -> 200 {ok, graceDays, agent} | 403
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
 *   ACCESS_CODES    (Secret)  codes de l'équipe, séparés par des virgules. Chaque code
 *                             peut porter une étiquette : "code=étiquette"
 *                             (ex. "K7M2P9=Agent-1,Q4X8ZD=Bunia-2"). Étiquette COURTE et
 *                             NON NOMINATIVE : jamais un nom de personne ni un numéro de
 *                             téléphone. Règle appliquée : 1 à 24 caractères parmi lettres,
 *                             chiffres, ".", "_", "-" (pas d'espace), 5 chiffres au plus ;
 *                             sinon l'étiquette est IGNORÉE (agent null) et signalée par la
 *                             page de diagnostic. Un code sans étiquette reste valable.
 *                             Une étiquette désigne le CODE utilisé, pas une personne : un
 *                             code peut être partagé, ce n'est pas une preuve d'identité.
 *                             Seule l'ÉTIQUETTE est enregistrée avec les envois (champ
 *                             agent des métadonnées KV), jamais le code.
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
/* Étiquette acceptée : courte, sans espace, 5 chiffres au plus (écarte noms complets et
   numéros de téléphone). Renvoie l'étiquette ou null. */
const LABEL_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,23}$/;
function validLabel(x){
  const s = String(x == null ? "" : x).trim();
  if (!LABEL_RE.test(s)) return null;
  if ((s.match(/[0-9]/g) || []).length > 5) return null;
  return s;
}
/* ACCESS_CODES : "code" ou "code=étiquette". Coupure au PREMIER "=" ; étiquette non conforme
   -> agent null, signalée (refusee: true) par la page de diagnostic. */
function accessEntries(value){
  return codeList(value).map(item => {
    const i = item.indexOf("=");
    if (i < 0) return { code: item, agent: null, refusee: false };
    const raw = item.slice(i + 1).trim();
    const agent = validLabel(raw);
    return { code: item.slice(0, i).trim(), agent, refusee: !!raw && !agent };
  }).filter(e => e.code);
}
/* Renvoie l'entrée correspondant au code (ou null). Parcourt TOUTE la liste, à durée
   constante par code, comme matchesAny. */
function findAccess(env, code){
  if (!code) return null;
  let found = null;
  for (const e of accessEntries(env.ACCESS_CODES)) if (safeEqual(e.code, code) && !found) found = e;
  return found;
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
      "Codes équipe : " + (accessEntries(env.ACCESS_CODES).length ? accessEntries(env.ACCESS_CODES).length + " (dont " + accessEntries(env.ACCESS_CODES).filter(e => e.agent).length + " avec étiquette)" : "NON (ACCESS_CODES manquant)") + ". " +
      (accessEntries(env.ACCESS_CODES).some(e => e.refusee) ? "ATTENTION : " + accessEntries(env.ACCESS_CODES).filter(e => e.refusee).length + " étiquette(s) ignorée(s) (non conformes : 24 caractères au plus, lettres, chiffres, . _ -, sans espace, 5 chiffres au plus ; jamais de nom ni de numéro de téléphone). " : "") +
      "Stockage KV : " + (env.DIGESTS ? "lié" : "NON lié (binding DIGESTS manquant)") + ". " +
      "Code admin : " + (env.ADMIN_CODE ? "oui" : "NON (ADMIN_CODE manquant, page d'administration inactive)") + ".";
    return new Response(diag, { status: 200, headers: Object.assign({ "Content-Type": "text/plain; charset=utf-8" }, corsHeaders(env)) });
  }
  const url = new URL(request.url);

  // --- Validation du code d'accès ---
  if (url.pathname === "/validate-code") {
    let body = {};
    try { body = await request.json(); } catch (e) {}
    const access = findAccess(env, String(body.code || "").trim());
    if (!access) return json(env, 403, { ok: false });
    return json(env, 200, { ok: true, graceDays: Number(env.GRACE_DAYS) || 14, agent: access.agent });
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
      const got = await env.DIGESTS.getWithMetadata("m:" + uid, "json");
      const manifest = got && got.value;
      if (!manifest) return json(env, 404, { ok: false, error: "Visite inconnue." });
      const manifestMeta = (got && got.metadata) || {};
      const stored = {};
      const agentsEntrees = new Set();
      let cursor;
      do {
        const page = await env.DIGESTS.list({ prefix: "e:" + uid + ":", cursor });
        for (const k of page.keys) stored[k.name.slice(("e:" + uid + ":").length)] = k.name;
        for (const k of page.keys) if (k.metadata && k.metadata.agent) agentsEntrees.add(k.metadata.agent);
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
      // agentRelais : étiquette du code utilisé pour le dernier envoi du manifeste (null :
      // code sans étiquette ou ancien envoi) ; agentsEntrees : étiquettes vues sur les entrées.
      // Ce sont des étiquettes de CODE (un code peut être partagé), pas des identités.
      const digest = Object.assign({}, manifest, { agentRelais: manifestMeta.agent || null, agentsEntrees: Array.from(agentsEntrees), entries, entreesManquantes: manquantes });
      delete digest.entrees;
      return json(env, 200, digest);
    }
    return json(env, 404, { ok: false, error: "Route inconnue." });
  }

  // --- Toutes les autres routes : code d'équipe obligatoire ---
  const code = (request.headers.get("X-Access-Code") || "").trim();
  const access = findAccess(env, code);
  if (!access) return json(env, 403, { ok: false, error: "code" });
  const agent = access.agent; // étiquette seulement — le code n'est jamais enregistré
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
        metadata: { type: entry.type || null, horodatage: entry.horodatage || null, taille: value.length, appareil: device, agent, recuLe: receivedAt }
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
        agent,
        operateur: validLabel(body.operateur),
        recuLe: receivedAt,
        entrees: Array.isArray(body.entrees) ? body.entrees.length : 0,
        corbeille: !!body.corbeille
      }
    });
    return json(env, 200, { ok: true, receivedAt });
  }

  return json(env, 404, { ok: false, error: "Route inconnue." });
}
