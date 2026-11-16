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


## Browser audience and automated traffic

The primary audience cards use the existing Cloudflare Web Analytics site
`68b036386f3841018058c0128192ef26` in account
`19a03bec57c0277e01e1e70e241576af`. These are public identifiers, not secrets.
No additional beacon or tracking script is installed by the admin report.

The same analytics API token also needs **Account > Account Analytics > Read**
for this account. Keep its existing read-only Zone Analytics permission. If
account access is missing, the audience section shows unavailable; it never
relabels raw totals as humans or substitutes zero for an API failure.

The browser query filters the site tag, exact site hostname and selected UTC
period, excludes /admin/ paths, and uses bot=0 for the audience estimate.
Detected bot browser page loads use bot=1 and remain separate. Visits are
not unique people. Unidentified automation and browser tests can remain;
ad blockers and disabled JavaScript can hide real visits.

The original edge totals are retained under a collapsed **Raw network traffic**
section. They include crawlers, scanners, tests, static requests and other
traffic and are not human counts. Edge totals minus beacon totals are never
reported as a bot count: they measure different populations. Raw network
country and popular-path tables remain explicitly unfiltered.

Historical browser data is limited to when Web Analytics was enabled and
Cloudflare retention. It cannot reconstruct human traffic before collection.

Official definitions: https://developers.cloudflare.com/web-analytics/data-metrics/dimensions/

