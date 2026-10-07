const DEFAULT_ORIGIN = "https://web--canecorsoancestry--4w9gl8jxj4yr.code.run";
// Bump this whenever public HTML/static layout assets must invalidate edge cache.
const EDGE_CACHE_VERSION = "image-galleries-v81"; // Photo-first public record presentation
const CACHE_FRESH_SECONDS = 900;
const CACHE_RETENTION_SECONDS = 604800;
const ORIGIN_GRACE_MS = 3500;
const AUTH_GRACE_MS = 450;
const READY_TIMEOUT_MS = 3500;
const AUTH_READY_TIMEOUT_MS = 4500;
const STATIC_EDGE_CACHE_SECONDS = 31536000;
const STATIC_BROWSER_CACHE_SECONDS = 300;
const SEARCH_CACHE_SECONDS = 60;
const CSRF_COOKIE_AGE = 31449600;
const CSRF_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
const BOT_RE = /(bot|crawler|spider|slurp|bingpreview|facebookexternalhit|twitterbot|linkedinbot)/i;
const PRIVATE_PREFIXES = ["/accounts/", "/member/", "/admin/", "/dashboard/", "/media/"];

function isLoginPath(pathname) {
  return pathname === "/accounts/login/";
}

function isPrefetchRequest(request) {
  const purpose = [
    request.headers.get("purpose") || "",
    request.headers.get("sec-purpose") || "",
  ].join(" ");
  return /prefetch/i.test(purpose);
}

function shouldWaitForOrigin(request, canCache) {
  const url = new URL(request.url);
  if (isHtmlNavigation(request) && !isLoginPath(url.pathname)) {
    return true;
  }
  return (
    canCache ||
    isBot(request) ||
    !isHtmlNavigation(request) ||
    isPrefetchRequest(request)
  );
}

function randomCsrfString(length = 32) {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  let value = "";
  for (const byte of bytes) value += CSRF_CHARS[byte % CSRF_CHARS.length];
  return value;
}

function csrfSecretFromRequest(request) {
  const cookie = request.headers.get("cookie") || "";
  const match = cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/i);
  const secret = match ? decodeURIComponent(match[1]) : "";
  if (secret.length === 32 && [...secret].every((char) => CSRF_CHARS.includes(char))) {
    return secret;
  }
  return randomCsrfString();
}

function maskCsrfSecret(secret) {
  const mask = randomCsrfString();
  let cipher = "";
  for (let index = 0; index < secret.length; index += 1) {
    const secretIndex = CSRF_CHARS.indexOf(secret[index]);
    const maskIndex = CSRF_CHARS.indexOf(mask[index]);
    cipher += CSRF_CHARS[(secretIndex + maskIndex) % CSRF_CHARS.length];
  }
  return mask + cipher;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isHtmlNavigation(request) {
  if (request.method !== "GET") return false;
  return (request.headers.get("accept") || "").includes("text/html");
}

function isBot(request) {
  return BOT_RE.test(request.headers.get("user-agent") || "");
}

function hasPrivateCookie(request) {
  const cookie = request.headers.get("cookie") || "";
  return /(?:^|;\s*)sessionid=/i.test(cookie);
}

function isPrivatePath(pathname) {
  return PRIVATE_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

function isSearchTrackingUrl(url) {
  return url.searchParams.size === 1 && url.searchParams.get("source") === "search";
}

function isCacheablePublicPath(url, request) {
  if (request.method !== "GET" || hasPrivateCookie(request)) return false;
  if (
    url.search &&
    !url.pathname.startsWith("/static/") &&
    url.pathname !== "/dogs/" &&
    url.pathname !== "/dogs/suggestions/" &&
    url.pathname !== "/kennels/" &&
    url.pathname !== "/pedigrees/virtual-mating/" &&
    !isSearchTrackingUrl(url)
  ) return false;
  const path = url.pathname;
  if (isPrivatePath(path)) return false;
  if (path.startsWith("/static/")) return true;
  if (path === "/" || path === "/dogs/" || path === "/dogs/suggestions/" || path === "/kennels/" || path === "/statistics/" || path === "/pedigrees/" || path === "/pedigrees/virtual-mating/") return true;
  if (/^\/dogs\/[-a-z0-9]+\/$/i.test(path)) return true;
  if (/^\/kennels\/[-a-z0-9]+\/$/i.test(path)) return true;
  if (/^\/litters\/[0-9a-f-]+\/$/i.test(path)) return true;
  if (/^\/pedigrees\/[-a-z0-9]+\/$/i.test(path)) return true;
  if (/^\/pedigrees\/[-a-z0-9]+\/descendants\/$/i.test(path)) return true;
  if (path === "/robots.txt" || path === "/sitemap.xml" || /^\/sitemap-[^/]+\.xml$/.test(path)) return true;
  return false;
}

function originUrlFor(request, env, pathOverride = null) {
  const incoming = new URL(request.url);
  const origin = new URL(env.ORIGIN_URL || DEFAULT_ORIGIN);
  origin.pathname = pathOverride || incoming.pathname;
  origin.search = pathOverride ? "" : incoming.search;
  return origin;
}

function originRequest(request, env, pathOverride = null) {
  const incoming = new URL(request.url);
  const target = originUrlFor(request, env, pathOverride);
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.set("x-forwarded-proto", "https");
  headers.set("x-forwarded-host", incoming.host);
  const clientIp = request.headers.get("cf-connecting-ip");
  if (clientIp) headers.set("x-forwarded-for", clientIp);
  headers.set("x-cca-edge", "1");
  if (env.ORIGIN_EDGE_SECRET) {
    headers.set("x-cca-origin-secret", env.ORIGIN_EDGE_SECRET);
  }

  const init = {
    method: pathOverride ? "GET" : request.method,
    headers,
    redirect: "manual",
  };
  if (!pathOverride && request.method !== "GET" && request.method !== "HEAD") {
    init.body = request.body;
  }
  return new Request(target.toString(), init);
}

function isDjangoResponse(response) {
  const timing = response.headers.get("server-timing") || "";
  return response.headers.has("x-request-id") || timing.includes("app;dur=");
}

function rewriteForVisitor(response, request, env, extraHeaders = {}) {
  const headers = new Headers(response.headers);
  const location = headers.get("location");
  if (location) {
    const originBase = new URL(env.ORIGIN_URL || DEFAULT_ORIGIN).origin;
    const visitorBase = new URL(request.url).origin;
    if (location.startsWith(originBase)) {
      headers.set("location", `${visitorBase}${location.slice(originBase.length)}`);
    }
  }
  for (const [key, value] of Object.entries(extraHeaders)) headers.set(key, value);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function cacheKey(request) {
  const url = new URL(request.url);
  url.hash = "";
  if (isSearchTrackingUrl(url)) url.search = "";
  url.searchParams.set("__cca_edge_v", EDGE_CACHE_VERSION);
  return new Request(url.toString(), { method: "GET" });
}

function cacheableOriginResponse(response) {
  if (response.status !== 200 || !isDjangoResponse(response)) return false;
  if (response.headers.has("set-cookie")) return false;
  const cacheControl = (response.headers.get("cache-control") || "").toLowerCase();
  return !cacheControl.includes("private") && !cacheControl.includes("no-store");
}

function edgeRetentionSeconds(request) {
  const url = new URL(request.url);
  if (url.pathname.startsWith("/static/")) return STATIC_EDGE_CACHE_SECONDS;
  if (url.search) return SEARCH_CACHE_SECONDS;
  return CACHE_RETENTION_SECONDS;
}

async function storeInEdgeCache(cache, key, response, request) {
  if (!cacheableOriginResponse(response)) return;
  const headers = new Headers(response.headers);
  headers.delete("set-cookie");
  headers.set("cache-control", `public, max-age=${edgeRetentionSeconds(request)}`);
  headers.set("x-cca-edge-stored-at", String(Date.now()));
  headers.set("x-cca-edge-cache", "STORED");
  await cache.put(
    key,
    new Response(response.clone().body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    }),
  );
}

function cachedForVisitor(cached, freshness, request) {
  const headers = new Headers(cached.headers);
  const url = new URL(request.url);
  if (url.pathname.startsWith("/static/")) {
    headers.set("cache-control", `public, max-age=${STATIC_BROWSER_CACHE_SECONDS}, stale-while-revalidate=3600`);
  } else if (url.search) {
    headers.set("cache-control", "public, max-age=15, stale-while-revalidate=60");
  } else {
    headers.set("cache-control", "no-cache, max-age=0, must-revalidate");
  }
  headers.set("x-cca-edge-cache", freshness);
  return new Response(cached.body, {
    status: cached.status,
    statusText: cached.statusText,
    headers,
  });
}

async function fetchOrigin(request, env, pathOverride = null) {
  return fetch(originRequest(request, env, pathOverride));
}

async function timedOriginGet(env, path, timeoutMs, userAgent, accept) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(new URL(path, env.ORIGIN_URL || DEFAULT_ORIGIN), {
      method: "GET",
      headers: {
        accept,
        "user-agent": userAgent,
        "x-cca-edge": "1",
        "x-cca-origin-secret": env.ORIGIN_EDGE_SECRET || "",
      },
      signal: controller.signal,
      redirect: "manual",
    });
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

async function wakeCriticalOrigin(env) {
  await Promise.allSettled([
    timedOriginGet(
      env,
      "/healthz/",
      READY_TIMEOUT_MS,
      "CaneCorsoAncestry-Edge-Warmup/1.1",
      "application/json",
    ),
    timedOriginGet(
      env,
      "/accounts/login/",
      AUTH_READY_TIMEOUT_MS,
      "CaneCorsoAncestry-Edge-Auth-Warmup/1.1",
      "text/html",
    ),
  ]);
}

async function originReady(env) {
  const response = await timedOriginGet(
    env,
    "/healthz/",
    READY_TIMEOUT_MS,
    "CaneCorsoAncestry-Edge-Ready/1.1",
    "application/json",
  );
  return Boolean(response && response.status === 200 && isDjangoResponse(response));
}

async function authReady(env) {
  const [health, login] = await Promise.all([
    timedOriginGet(
      env,
      "/healthz/",
      AUTH_READY_TIMEOUT_MS,
      "CaneCorsoAncestry-Edge-Auth-Ready/1.1",
      "application/json",
    ),
    timedOriginGet(
      env,
      "/accounts/login/",
      AUTH_READY_TIMEOUT_MS,
      "CaneCorsoAncestry-Edge-Auth-Ready/1.1",
      "text/html",
    ),
  ]);
  return Boolean(
    health &&
      login &&
      health.status === 200 &&
      login.status === 200 &&
      isDjangoResponse(health) &&
      isDjangoResponse(login),
  );
}

function authWarmingPage(request) {
  const url = new URL(request.url);
  const secret = csrfSecretFromRequest(request);
  const token = maskCsrfSecret(secret);
  const rawNext = url.searchParams.get("next") || "";
  const safeNext =
    rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "";
  const nextField = safeNext
    ? `<input type="hidden" name="next" value="${escapeHtml(safeNext)}">`
    : "";
  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in · Cane Corso Ancestry</title>
<style>
:root{color-scheme:dark;--bg:#151515;--panel:#1d1d1d;--gold:#c7a45a;--ivory:#f4efe4;--muted:#aaa396;--line:#373126}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 50% 8%,#28241d 0,#151515 38%,#101010 100%);font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ivory);padding:24px}
main{width:min(440px,100%)}.brand{text-align:center;margin-bottom:22px}.mark{width:68px;height:68px;border:1px solid rgba(199,164,90,.55);border-radius:50%;display:grid;place-items:center;margin:0 auto 15px;font-family:Georgia,serif;font-size:31px;color:var(--gold)}
.card{background:rgba(29,29,29,.96);border:1px solid var(--line);border-radius:18px;padding:26px;box-shadow:0 18px 60px rgba(0,0,0,.28)}
.eyebrow{color:var(--gold);font-size:12px;letter-spacing:.12em;text-transform:uppercase;margin:0 0 8px}h1{font-family:Georgia,serif;font-weight:500;font-size:34px;margin:0 0 8px}.sub{color:var(--muted);line-height:1.5;margin:0 0 20px}
label{display:block;margin:14px 0 7px;font-size:14px}input{width:100%;border:1px solid #474035;background:#111;color:var(--ivory);border-radius:10px;padding:13px 14px;font-size:16px;outline:none}input:focus{border-color:var(--gold);box-shadow:0 0 0 3px rgba(199,164,90,.12)}
button{width:100%;margin-top:18px;border:0;border-radius:10px;background:var(--gold);color:#16130e;font-weight:750;font-size:15px;padding:13px 16px;cursor:pointer}
.status{display:flex;gap:8px;align-items:center;margin-top:15px;color:var(--muted);font-size:13px}.dot{width:8px;height:8px;border-radius:50%;background:var(--gold);box-shadow:0 0 0 4px rgba(199,164,90,.12);animation:pulse 1.4s ease-in-out infinite}
.links{margin:18px 0 0;text-align:center;font-size:13px}.links a{color:var(--ivory)}@keyframes pulse{50%{opacity:.35;transform:scale(.85)}}
</style>
</head>
<body>
<main>
<div class="brand"><div class="mark" aria-hidden="true">C</div><strong>Cane Corso Ancestry</strong></div>
<section class="card">
<p class="eyebrow">Member access</p>
<h1>Sign in</h1>
<p class="sub">You can enter your details now. The secure Django service is starting in the background.</p>
<form method="post" action="">
<input type="hidden" name="csrfmiddlewaretoken" value="${token}">
${nextField}
<label for="id_username">Email</label>
<input id="id_username" name="username" type="email" autocomplete="email" autofocus required>
<label for="id_password">Password</label>
<input id="id_password" name="password" type="password" autocomplete="current-password" required>
<button id="submit" type="submit">Sign in</button>
</form>
<div class="status" id="status" role="status" aria-live="polite"><span class="dot"></span><span>Preparing secure sign-in…</span></div>
<p class="links"><a href="/member/signup/">Create a member account</a></p>
</section>
</main>
<script>
const status=document.querySelector("#status span:last-child");
async function check(){
  try{
    const r=await fetch("/__edge/auth-ready",{cache:"no-store",credentials:"same-origin"});
    if(r.ok){status.textContent="Secure sign-in is ready.";return}
  }catch(e){}
  setTimeout(check,1600)
}
setTimeout(check,500);
document.querySelector("form").addEventListener("submit",()=>{document.getElementById("submit").textContent="Signing in…"});
</script>
</body>
</html>`;
  return new Response(html, {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "set-cookie": `csrftoken=${secret}; Max-Age=${CSRF_COOKIE_AGE}; Path=/; Secure; HttpOnly; SameSite=Lax`,
      "x-robots-tag": "noindex, nofollow",
      "x-cca-edge-warming": "auth",
      "content-security-policy":
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
      "referrer-policy": "same-origin",
      "x-content-type-options": "nosniff",
    },
  });
}

function warmingPage(request) {
  const url = new URL(request.url);
  const next = `${url.pathname}${url.search}`;
  const safeNext = JSON.stringify(next).replace(/</g, "\\u003c");
  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Preparing Cane Corso Ancestry</title>
<style>
:root{color-scheme:dark;--bg:#151515;--panel:#1d1d1d;--gold:#c7a45a;--ivory:#f4efe4;--muted:#b7b0a3}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 50% 10%,#28241d 0,#151515 38%,#101010 100%);font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ivory);padding:24px}
main{width:min(760px,100%);text-align:center}.mark{width:74px;height:74px;border:1px solid rgba(199,164,90,.55);border-radius:50%;display:grid;place-items:center;margin:0 auto 22px;font-family:Georgia,serif;font-size:34px;color:var(--gold);box-shadow:0 0 0 8px rgba(199,164,90,.05)}
h1{font-family:Georgia,serif;font-size:clamp(32px,6vw,54px);font-weight:500;margin:0 0 12px;letter-spacing:.02em}p{color:var(--muted);font-size:17px;line-height:1.65;margin:0 auto;max-width:600px}.status{margin:28px auto 18px;color:var(--ivory);font-size:14px;letter-spacing:.08em;text-transform:uppercase}
.track{width:min(420px,82vw);height:5px;background:#2a2926;border-radius:999px;overflow:hidden;margin:0 auto 34px}.bar{height:100%;width:34%;background:linear-gradient(90deg,transparent,var(--gold),transparent);animation:move 1.25s ease-in-out infinite}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:18px}.card{height:86px;border:1px solid #2f2c26;border-radius:14px;background:linear-gradient(110deg,#1b1b1b 25%,#24211c 45%,#1b1b1b 65%);background-size:220% 100%;animation:shine 1.8s linear infinite}.hint{font-size:13px;color:#8f887c;margin-top:18px}
button{display:none;margin:22px auto 0;border:1px solid var(--gold);background:transparent;color:var(--ivory);padding:11px 18px;border-radius:999px;cursor:pointer}
@keyframes move{0%{transform:translateX(-120%)}100%{transform:translateX(300%)}}@keyframes shine{0%{background-position:200% 0}100%{background-position:-20% 0}}@media(max-width:540px){.cards{grid-template-columns:1fr}.card:nth-child(n+2){display:none}}
</style>
</head>
<body>
<main>
<div class="mark" aria-hidden="true">C</div>
<h1>Cane Corso Ancestry</h1>
<p>Preparing the live pedigree tools. Public pedigree information is loaded as soon as it is ready.</p>
<div class="status" id="status" role="status" aria-live="polite">Connecting to the pedigree database…</div>
<div class="track" aria-hidden="true"><div class="bar"></div></div>
<div class="cards" aria-hidden="true"><div class="card"></div><div class="card"></div><div class="card"></div></div>
<p class="hint">This page continues automatically.</p>
<button id="retry" type="button">Try again</button>
</main>
<script>
const next=${safeNext};let tries=0;const status=document.getElementById("status");const retry=document.getElementById("retry");
async function check(){tries+=1;try{const r=await fetch("/__edge/ready",{cache:"no-store",credentials:"same-origin"});if(r.ok){location.replace(next);return}}catch(e){}if(tries<45){setTimeout(check,1800)}else{status.textContent="The live service is taking longer than expected.";retry.style.display="block"}}
retry.addEventListener("click",()=>location.reload());setTimeout(check,700);
</script>
</body>
</html>`;
  return new Response(html, {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-robots-tag": "noindex, nofollow",
      "retry-after": "2",
      "x-cca-edge-warming": "1",
      "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
      "referrer-policy": "same-origin",
      "x-content-type-options": "nosniff",
    },
  });
}

async function refreshCachedPage(request, env, cache, key) {
  try {
    const response = await fetchOrigin(request, env);
    if (cacheableOriginResponse(response)) await storeInEdgeCache(cache, key, response, request);
  } catch {
    // Stale cached content remains available if refresh fails.
  }
}

async function handleRequest(request, env, ctx) {
  const url = new URL(request.url);

  if (url.pathname === "/__edge/health") {
    return Response.json(
      { status: "ok", service: "site-edge", origin: env.ORIGIN_URL || DEFAULT_ORIGIN },
      { headers: { "cache-control": "no-store" } },
    );
  }

  if (url.pathname === "/__edge/ready") {
    const ready = await originReady(env);
    return Response.json(
      { ready },
      { status: ready ? 200 : 202, headers: { "cache-control": "no-store" } },
    );
  }

  if (url.pathname === "/__edge/auth-ready") {
    const ready = await authReady(env);
    return Response.json(
      { ready },
      { status: ready ? 200 : 202, headers: { "cache-control": "no-store" } },
    );
  }

  if (url.pathname === "/__edge/warm-auth") {
    ctx.waitUntil(wakeCriticalOrigin(env));
    return new Response(null, {
      status: 204,
      headers: { "cache-control": "no-store" },
    });
  }

  const canCache = isCacheablePublicPath(url, request);
  const cache = caches.default;
  const key = canCache ? cacheKey(request) : null;

  if (canCache) {
    const cached = await cache.match(key);
    if (cached) {
      const storedAt = Number(cached.headers.get("x-cca-edge-stored-at") || "0");
      const ageSeconds = Math.max(0, (Date.now() - storedAt) / 1000);
      if (ageSeconds > CACHE_FRESH_SECONDS) {
        ctx.waitUntil(refreshCachedPage(request, env, cache, key));
        return cachedForVisitor(cached, "STALE", request);
      }
      // Fresh cache hits must not amplify traffic to Django. The scheduled
      // Worker trigger keeps the origin/auth path warm every four minutes.
      // Search popularity is intentionally approximate on cached hits rather
      // than recomputing an expensive dog profile only to increment a counter.
      return cachedForVisitor(cached, "HIT", request);
    }
  }

  const originPromise = fetchOrigin(request, env);
  const loginRequest = isLoginPath(url.pathname) && request.method === "GET";
  const mustWaitForOrigin = shouldWaitForOrigin(request, canCache);

  if (mustWaitForOrigin) {
    const response = await originPromise;
    if (canCache) ctx.waitUntil(storeInEdgeCache(cache, key, response, request));
    return rewriteForVisitor(response, request, env, { "x-cca-edge-cache": canCache ? "MISS" : "BYPASS" });
  }

  const first = await Promise.race([
    originPromise.then((response) => ({ type: "origin", response })).catch(() => ({ type: "error" })),
    delay(loginRequest ? AUTH_GRACE_MS : ORIGIN_GRACE_MS).then(() => ({ type: "timeout" })),
  ]);

  if (first.type === "origin" && isDjangoResponse(first.response)) {
    if (canCache) ctx.waitUntil(storeInEdgeCache(cache, key, first.response, request));
    return rewriteForVisitor(first.response, request, env, { "x-cca-edge-cache": canCache ? "MISS" : "BYPASS" });
  }

  if (first.type === "timeout") {
    ctx.waitUntil(wakeCriticalOrigin(env));
    ctx.waitUntil(
      originPromise
        .then((response) =>
          canCache ? storeInEdgeCache(cache, key, response, request) : undefined,
        )
        .catch(() => undefined),
    );
  } else {
    ctx.waitUntil(wakeCriticalOrigin(env));
  }
  return loginRequest ? authWarmingPage(request) : warmingPage(request);
}

export { hasPrivateCookie, isSearchTrackingUrl, isCacheablePublicPath, shouldWaitForOrigin, cacheKey, originRequest, timedOriginGet, authWarmingPage };

export default {
  fetch(request, env, ctx) {
    return handleRequest(request, env, ctx);
  },
  scheduled(_event, env, ctx) {
    ctx.waitUntil(wakeCriticalOrigin(env));
  },
};
