#!/usr/bin/env python3
"""Search public archives for the 48 missing dog uploads. Never mutate production."""
import concurrent.futures as cf
import datetime as dt
import gzip
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlencode, unquote
from urllib.request import Request, urlopen

DOC=Path("docs/operations/MISSING_DOG_PHOTO_RECOVERY_2026-11-20.md")
OUT=Path("artifacts/cca-photo-cache-recovery")
OUT.mkdir(parents=True,exist_ok=True)
MAX=20*1024*1024
ERRORS=[]
def get(url, *, extra=None, limit=MAX):
    headers={"User-Agent":"Mozilla/5.0 (CaneCorsoAncestry public-photo recovery)"}
    headers.update(extra or {})
    with urlopen(Request(url,headers=headers),timeout=18) as r:
        data=r.read(limit+1)
        if len(data)>limit: raise ValueError("Too many bytes")
        return data

def targets():
    found=[]
    dog=None
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "): dog=line[4:].split(" (",1)[0]
        if not line.startswith("- "+chr(96)): continue
        key=line.split(chr(96),2)[1]
        if not key.startswith(("dogs/","submissions/")): continue
        if "— PRIMARY" not in line and "— gallery" not in line: continue
        h=re.search(r"[0-9a-f]{64}",line)
        found.append({"dog":dog,"key":key,"sha256":h.group() if h else ""})
    assert len(found)==48, f"Expected 48 missing photos, found {len(found)}"
    return found
def target_of(url,refs):
    u=unquote(url)
    return next((x for x in refs if x["key"] in u),None)
def safe(fn,arg):
    try: return fn(arg)
    except Exception as exc: return {"error":f"{type(exc).__name__}: {str(exc)[:160]}"}
def wayback(refs):
    prefixes=["canecorsoancestry.com/media/dogs/*",
        "canecorsoancestry.com/media/submissions/*",
        "www.canecorsoancestry.com/media/dogs/*",
        "canecorsoancestry-site-edge.aighewieghosa111.workers.dev/media/dogs/*",
        "media.canecorsoancestry.com/_thumb/dogs/*",
        "media.canecorsoancestry.com/_media/dogs/*"]
    def query(pattern):
        params=urlencode({"url":pattern,"output":"json","filter":"statuscode:200",
                          "fl":"timestamp,original,mimetype,statuscode","collapse":"urlkey"})
        rows=json.loads(get("https://web.archive.org/cdx/search/cdx?"+params,limit=5_000_000))
        if rows and rows[0][0]=="timestamp": rows=rows[1:]
        hits=[]
        for row in rows:
            if len(row)<2: continue
            t=target_of(row[1],refs)
            if t: hits.append({"kind":"wayback","target":t,
                               "timestamp":row[0],"url":row[1]})
        return hits
    hits=[]
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        for pattern,result in zip(prefixes,pool.map(lambda p:safe(query,p),prefixes)):
            if isinstance(result,dict):
                ERRORS.append({"source":"wayback","pattern":pattern,**result})
                print("Wayback unavailable:",pattern,result["error"],flush=True)
            else:
                hits.extend(result)
                print("Wayback captures:",pattern,len(result),flush=True)
    return hits
def commoncrawl(refs):
    try:
        colls=json.loads(get("https://index.commoncrawl.org/collinfo.json",limit=500_000))
        colls=[x for x in colls if x.get("id","").startswith("CC-MAIN-2026-")][:3]
    except Exception as exc:
        ERRORS.append({"source":"commoncrawl","error":str(exc)[:160]})
        print("Common Crawl archive listing unavailable",flush=True)
        return []
    prefixes=["canecorsoancestry.com/media/dogs/*",
        "canecorsoancestry.com/media/submissions/*",
        "media.canecorsoancestry.com/_thumb/dogs/*",
        "media.canecorsoancestry.com/_media/dogs/*"]
    jobs=[(coll,pattern) for coll in colls for pattern in prefixes]
    def query(item):
        coll,pattern=item
        data=get(coll["cdx-api"]+"?"+urlencode({"url":pattern,"output":"json"}),limit=4_000_000)
        hits=[]
        for line in data.splitlines():
            try: row=json.loads(line)
            except ValueError: continue
            t=target_of(row.get("url",""),refs)
            if t and str(row.get("status"))=="200":
                hits.append({"kind":"commoncrawl","target":t,"url":row["url"],
                             "filename":row.get("filename"),"offset":row.get("offset"),
                             "length":row.get("length")})
        return hits
    hits=[]
    with cf.ThreadPoolExecutor(max_workers=5) as pool:
        for job,res in zip(jobs,pool.map(lambda j:safe(query,j),jobs)):
            if isinstance(res,dict):
                ERRORS.append({"source":"commoncrawl","collection":job[0]["id"],
                               "pattern":job[1][0:75],**res})
            else: hits.extend(res)
    print("Common Crawl indexed image captures:",len(hits),flush=True)
    return hits
def cached_image(hit):
    if hit["kind"]=="wayback":
        url="https://web.archive.org/web/"+hit["timestamp"]+"id_/"+hit["url"]
        return get(url)
    offset=int(hit["offset"]); length=int(hit["length"])
    if length>MAX+3000: raise ValueError("Huge WARC record")
    gz=get("https://data.commoncrawl.org/"+hit["filename"],
           extra={"Range":f"bytes={offset}-{offset+length-1}"},limit=length+1000)
    warc=gzip.decompress(gz)
    i=warc.find(b"\r\n\r\n")
    if i<0: raise ValueError("Malformed WARC")
    http=warc[i+4:]
    i=http.find(b"\r\n\r\n")
    if i<0: raise ValueError("Malformed HTTP")
    return http[i+4:]
def image_ok(body):
    return (body.startswith((bytes.fromhex("ffd8ff"),bytes.fromhex("89504e470d0a1a0a"),
                             b"GIF87a",b"GIF89a")) or
            body[:4]==b"RIFF" and body[8:12]==b"WEBP" or b"ftypavif" in body[:24])
def recover(hit):
    data=cached_image(hit)
    if len(data)<100 or not image_ok(data): raise ValueError("Not image bytes")
    t=hit["target"]
    digest=hashlib.sha256(data).hexdigest()
    exact=bool(t["sha256"]) and digest==t["sha256"]
    dst=OUT/("exact" if exact else "unverified")/t["key"]
    if not exact: dst=dst.with_name(dst.stem+"-"+digest[:12]+dst.suffix)
    dst.parent.mkdir(parents=True,exist_ok=True)
    if not dst.exists(): dst.write_bytes(data)
    return {"key":t["key"],"dog":t["dog"],"exact":exact,
            "sha256":digest,"source":hit["kind"],"source_url":hit["url"],
            "bytes":len(data),"file":str(dst.relative_to(OUT))}
def main():
    refs=targets()
    hits=wayback(refs)+commoncrawl(refs)
    done=[];seen=set()
    for hit in hits:
        identity=(hit["kind"],hit["target"]["key"],hit.get("timestamp"),hit.get("offset"))
        if identity in seen: continue
        seen.add(identity)
        try:
            row=recover(hit)
            done.append(row)
            print("EXACT" if row["exact"] else "UNVERIFIED","candidate",row["key"],flush=True)
        except Exception as exc:
            ERRORS.append({"source":hit["kind"],"key":hit["target"]["key"],
                           "read_error":str(exc)[:160]})
    exact=[x for x in done if x["exact"]]
    unverified=[x for x in done if not x["exact"]]
    report={"checked_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
            "target_count":len(refs),"archive_url_matches":len(hits),
            "exact_originals":exact,"unverified_cached":unverified,"errors":ERRORS}
    (OUT/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    summary=f"Targets: {len(refs)}; archive URLs: {len(hits)}; exact originals: {len(exact)}; unverified cached copies: {len(unverified)}; archive/API errors: {len(ERRORS)}"
    (OUT/"SUMMARY.txt").write_text(summary+"\nNo production records or files changed.\n")
    print(summary,flush=True)
if __name__=="__main__": main()
