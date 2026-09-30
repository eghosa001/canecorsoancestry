const DEFAULT_ORIGIN = "https://canecorsoancestry.onrender.com";
const CACHE_FRESH_SECONDS = 300;
const CACHE_RETENTION_SECONDS = 86400;
const ORIGIN_GRACE_MS = 1800;
const READY_TIMEOUT_MS = 3500;
const BOT_RE = /(bot|crawler|spider|slurp|bingpreview|facebookexternalhit|twitterbot|linkedinbot)/i;
const PRIVATE_PREFIXES = ["/accounts/", "/member/", "/admin/", "/dashboard/", "/media/"];

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
  return /(?:^|;\s*)(sessionid|csrftoken)=/i.test(cookie);
}

function isPrivatePath(pathname) {
  return PRIVATE_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

function isCacheablePublicPath(url, request) {
  if (request.method !== "GET" || url.search || hasPrivateCookie(request)) return false;
  const path = url.pathname;
  if (isPrivatePath(path)) return false;
  if (path.startsWith("/static/")) return true;
  if (path === "/" || path === "/dogs/" || path === "/kennels/" || path === "/statistics/" || path === "/pedigrees/") return true;
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
  const target = originUrlFor(request, env, pathOverride);
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.set("x-forwarded-proto", "https");
  const clientIp = request.headers.get("cf-connecting-ip");
  if (clientIp) headers.set("x-forwarded-for", clientIp);
  headers.set("x-cca-edge", "1");

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
  return new Request(url.toString(), { method: "GET" });
}

function cacheableOriginResponse(response) {
  if (response.status !== 200 || !isDjangoResponse(response)) return false;
  if (response.headers.has("set-cookie")) return false;
  const cacheControl = (response.headers.get("cache-control") || "").toLowerCase();
  return !cacheControl.includes("private") && !cacheControl.includes("no-store");
}

async function storeInEdgeCache(cache, key, response) {
  if (!cacheableOriginResponse(response)) return;
  const headers = new Headers(response.headers);
  headers.delete("set-cookie");
  headers.set("cache-control", `public, max-age=${CACHE_RETENTION_SECONDS}`);
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

function cachedForVisitor(cached, freshness) {
  const headers = new Headers(cached.headers);
  headers.set("cache-control", "public, max-age=30, stale-while-revalidate=300");
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

async function wakeOrigin(env) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), READY_TIMEOUT_MS);
  try {
    await fetch(new URL("/healthz/", env.ORIGIN_URL || DEFAULT_ORIGIN), {
      method: "GET",
      headers: {
        accept: "application/json",
        "user-agent": "CaneCorsoAncestry-Edge-Warmup/1.0",
      },
      signal: controller.signal,
      redirect: "manual",
    });
  } catch {
    // Reaching the sleeping origin is itself useful: it starts the Render wake-up.
  } finally {
    clearTimeout(timer);
  }
}

async function originReady(env) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), READY_TIMEOUT_MS);
  try {
    const response = await fetch(new URL("/healthz/", env.ORIGIN_URL || DEFAULT_ORIGIN), {
      method: "GET",
      headers: {
        accept: "application/json",
        "user-agent": "CaneCorsoAncestry-Edge-Ready/1.0",
      },
      signal: controller.signal,
      redirect: "manual",
    });
    return response.status === 200 && isDjangoResponse(response);
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
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
    if (cacheableOriginResponse(response)) await storeInEdgeCache(cache, key, response);
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

  const canCache = isCacheablePublicPath(url, request);
  const cache = caches.default;
  const key = canCache ? cacheKey(request) : null;

  if (canCache) {
    const cached = await cache.match(key);
    if (cached) {
      const storedAt = Number(cached.headers.get("x-cca-edge-stored-at") || "0");
      const ageSeconds = Math.max(0, (Date.now() - storedAt) / 1000);
      ctx.waitUntil(wakeOrigin(env));
      if (ageSeconds > CACHE_FRESH_SECONDS) {
        ctx.waitUntil(refreshCachedPage(request, env, cache, key));
        return cachedForVisitor(cached, "STALE");
      }
      return cachedForVisitor(cached, "HIT");
    }
  }

  const originPromise = fetchOrigin(request, env);
  const mustWaitForOrigin = isBot(request) || !isHtmlNavigation(request);

  if (mustWaitForOrigin) {
    const response = await originPromise;
    if (canCache) ctx.waitUntil(storeInEdgeCache(cache, key, response));
    return rewriteForVisitor(response, request, env, { "x-cca-edge-cache": canCache ? "MISS" : "BYPASS" });
  }

  const first = await Promise.race([
    originPromise.then((response) => ({ type: "origin", response })).catch(() => ({ type: "error" })),
    delay(ORIGIN_GRACE_MS).then(() => ({ type: "timeout" })),
  ]);

  if (first.type === "origin" && isDjangoResponse(first.response)) {
    if (canCache) ctx.waitUntil(storeInEdgeCache(cache, key, first.response));
    return rewriteForVisitor(first.response, request, env, { "x-cca-edge-cache": canCache ? "MISS" : "BYPASS" });
  }

  if (first.type === "timeout") {
    ctx.waitUntil(
      originPromise
        .then((response) => (canCache ? storeInEdgeCache(cache, key, response) : undefined))
        .catch(() => undefined),
    );
  } else {
    ctx.waitUntil(wakeOrigin(env));
  }
  return warmingPage(request);
}

export default {
  fetch(request, env, ctx) {
    return handleRequest(request, env, ctx);
  },
};
