# Cloudflare visitor traffic in the Django admin

Open `https://canecorsoancestry.com/admin/traffic/` using a **super-admin**
account. The admin home also contains a Website traffic link.

## Required production configuration

Add these environment variables to the Oracle Django origin (not Cloudflare
Worker public bindings, the repository, or an HTML page):

- `CCA_TRAFFIC_ZONE_ID`: Cloudflare zone ID for canecorsoancestry.com.
- `CCA_TRAFFIC_API_TOKEN`: a Cloudflare API token granting read-only Zone
  Analytics access, restricted to this zone.

Then restart the Django service. Never paste the credential into public
issues or frontend configuration. The older environment variable names
`CLOUDFLARE_ZONE_ID` and `CLOUDFLARE_ANALYTICS_API_TOKEN` are accepted too.

Until the token and zone ID are configured, the admin page shows a setup
message rather than made-up traffic numbers. Invalid permissions or API
outages produce an explicit unavailable state.

## How the metrics work

The integration queries existing Cloudflare HTTP analytics. It adds **no**
tracking script, no database write, no schema migrations, and no extra
requests from public site visitors. Queries run only for authenticated
super-admins and are cached for five minutes.

- Page views: Cloudflare's daily HTML-page estimate.
- HTTP requests: requests served by the zone, including assets and bots.
- Estimated unique visitors today: daily unique count from Cloudflare.
- Average daily unique visitors: mean of daily unique estimates, **not** a
  distinct user count across seven or thirty days.
- Popular public URLs: HTTP request counts for known public route prefixes.
- Country table: HTTP request count by country for the site hostname.

All periods use UTC and report current-day data where available. Automated
traffic can be represented in these Cloudflare estimates, and Cloudflare
data availability depends on plan and historical retention. Google Search
Console clicks are not visitor counts.
