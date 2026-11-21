#!/usr/bin/env python3
"""Read-only search of signed Cloudflare media originals and edge thumbnails."""
import base64, collections, concurrent.futures, hashlib, hmac, json, os, re, time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
OUT=Path("artifacts/cca-signed-photo-cache-recovery")
OUT.mkdir(parents=True,exist_ok=True)
DOC=Path("docs/operations/MISSING_DOG_PHOTO_RECOVERY_2026-11-20.md")
KEY=base64.b64encode(os.environ["DJANGO_SECRET_KEY"].encode())
assert len(KEY)>20
def refs():
    result=[];dog=""
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):dog=line[4:].split(" (",1)[0]
        if not line.startswith("- "+chr(96)):continue
        key=line.split(chr(96),2)[1]
        if not key.startswith(("dogs/","submissions/")):continue
        if "— PRIMARY" not in line and "— gallery" not in line:continue
        h=re.search(r"[a-f0-9]{64}",line)
        result.append({"key":key,"dog":dog,"expected":h.group() if h else ""})
    assert len(result)==48
    return result
def url(key,kind):
    exp=str(int(time.time())+300)
    if kind=="original":
        message="\n".join(("GET",key,exp))
        path="/_media/"+quote(key,safe="/")
        params={"expires":exp}
    else:
        message="\n".join(("GET",key,kind,exp))
        path="/_thumb/"+quote(key,safe="/")
        params={"variant":kind,"expires":exp}
    params["signature"]=hmac.new(KEY,message.encode(),hashlib.sha256).hexdigest()
    return "https://media.canecorsoancestry.com"+path+"?"+urlencode(params)
def looks_like_image(b):
    return (b.startswith((bytes.fromhex("ffd8ff"),bytes.fromhex("89504e470d0a1a0a"),b"GIF87a",b"GIF89a"))
            or b[:4]==b"RIFF" and b[8:12]==b"WEBP" or b"ftypavif" in b[:24])
def get(job):
    ref,kind=job
    req=Request(url(ref["key"],kind),headers={"User-Agent":"Mozilla/5.0 (CCA photo recovery)",
                                             "Accept":"image/avif,image/webp,image/jpeg,image/*"})
    try:
        with urlopen(req,timeout=9) as response:
            image=response.read(20*1024*1024+1)
            if len(image)<100 or len(image)>20*1024*1024 or not looks_like_image(image):
                return {"status":"not-image","key":ref["key"],"kind":kind}
            sha=hashlib.sha256(image).hexdigest()
            exact=bool(ref["expected"]) and sha==ref["expected"]
            state="exact" if exact else "unverified"
            dest=OUT/state/ref["key"]
            if not exact:
                dest=dest.with_name(dest.stem+"-"+kind+"-"+sha[:12]+".webp")
            dest.parent.mkdir(parents=True,exist_ok=True)
            if not dest.exists():dest.write_bytes(image)
            return {"status":state,"key":ref["key"],"dog":ref["dog"],
                    "variant":kind,"sha256":sha,"bytes":len(image),
                    "file":str(dest.relative_to(OUT)),
                    "cache_header":response.headers.get("x-cca-image-cache","")}
    except HTTPError as e:
        return {"status":str(e.code),"key":ref["key"],"variant":kind}
    except (URLError,TimeoutError,OSError) as e:
        return {"status":type(e).__name__,"key":ref["key"],"variant":kind}
def main():
    records=refs()
    jobs=[(r,"original") for r in records]
    jobs.extend((r,variant) for r in records if r["key"].startswith("dogs/")
                for variant in ("card","portrait"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        results=list(pool.map(get,jobs))
    counts=collections.Counter(x["status"] for x in results)
    report={"missing":len(records),"probes":len(jobs),"result_counts":dict(counts),
            "restored_or_candidated":[x for x in results if x["status"] in ("exact","unverified")],
            "unavailable":[x for x in results if x["status"] not in ("exact","unverified")]}
    (OUT/"report.json").write_text(json.dumps(report,indent=2))
    print("Signed photo/cache probes:",len(jobs),flush=True)
    print("Status counts:",dict(counts),flush=True)
    print("Exact originals:",counts["exact"],"unverified cached:",counts["unverified"],flush=True)
    print("No production media or database changed.",flush=True)
if __name__=="__main__":main()
