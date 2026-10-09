#!/usr/bin/env bash
# Prove Oracle Django can use local Postgres on an internal Podman bridge.
# This does not change live Oracle Django, origin routing, or Supabase.
set -euo pipefail
umask 077
[[ "$GITHUB_REPOSITORY" == "eghosa001/canecorsoancestry" &&
   "$GITHUB_REF" == "refs/heads/main" &&
   "$(id -un)" == "opc" && "$(uname -m)" == "aarch64" ]] || exit 2
sudo -n true
sudo -n systemctl is-active --quiet cca-oracle-staging.service
sudo -n test -s /etc/cca/pgshadow-django.env
sudo -n podman container exists cca-pg-shadow
if ! sudo -n podman network exists cca-private; then
  sudo -n podman network create cca-private >/dev/null
fi
if ! sudo -n podman inspect --format '{{json .NetworkSettings.Networks}}' cca-pg-shadow | grep -q '"cca-private"'; then
  sudo -n podman network connect cca-private cca-pg-shadow
fi
sudo -n podman exec cca-pg-shadow pg_isready -h 127.0.0.1 -U cca_shadow_admin -d cca_shadow >/dev/null
# Derived root-only env file; no credentials printed or entered in shell argv.
sudo -n python3 - <<'PY'
from pathlib import Path
source=Path("/etc/cca/pgshadow-django.env")
target=Path("/etc/cca/pgshadow-private-django.env")
if target.exists():
    raise SystemExit("Private bridge probe env already created; do not overwrite")
values={}
for line in source.read_text().splitlines():
    if "=" not in line:continue
    k,v=line.split("=",1);values[k]=v
url=values["DATABASE_URL"]
assert "@127.0.0.1:15432/cca_shadow" in url
values["DATABASE_URL"]=url.replace("@127.0.0.1:15432/cca_shadow","@cca-pg-shadow:5432/cca_shadow")
with target.open("x") as f:
    for k,v in values.items():f.write(k+"="+v+"\n")
target.chmod(0o600)
PY
image="$(sudo -n podman inspect --format '{{.ImageName}}' cca-oracle-staging)"
[[ "$image" == localhost/cca-oracle:* ]] || exit 2
sudo -n podman run --rm -i --network cca-private \
  --env-file /etc/cca/pgshadow-private-django.env \
  "$image" python - <<'PY'
import os,statistics,time,urllib.request
import django
django.setup()
from django.db import connection
from django.test import Client
with connection.cursor() as c:
    samples=[]
    for _ in range(15):
        st=time.perf_counter();c.execute("SELECT 1");assert c.fetchone()==(1,)
        samples.append((time.perf_counter()-st)*1000)
print("private_bridge_sql_median_ms=%.3f"%statistics.median(samples))
client=Client(HTTP_HOST="canecorsoancestry-site-edge.aighewieghosa111.workers.dev",
    HTTP_X_FORWARDED_PROTO="https",HTTP_X_CCA_EDGE="1",
    HTTP_X_CCA_ORIGIN_SECRET=os.environ["DJANGO_SECRET_KEY"])
for path in ("/","/accounts/login/","/pedigrees/virtual-mating/","/dogs/?q=Branco"):
    response=client.get(path)
    print("private_bridge_route="+path+" status="+str(response.status_code))
    assert response.status_code==200
with urllib.request.urlopen(
    urllib.request.Request(
        "https://canecorsoancestry-edge.aighewieghosa111.workers.dev/healthz/",
        headers={"User-Agent":"CaneCorsoAncestry-Preflight/1.0"}
    ),timeout=12
) as response:
    print("private_bridge_R2_network_http="+str(response.status))
    assert response.status==200
print("SUCCESS: app can reach local DB and public R2 over isolated network.")
PY
echo "PASS: No production database or Oracle web container switched."
