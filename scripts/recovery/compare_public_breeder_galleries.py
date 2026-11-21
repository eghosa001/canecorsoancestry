#!/usr/bin/env python3
"""Read-only verification of independent named-dog photo galleries against missing uploads.

Only exactly matching SHA256 files are retained. Public URLs for nonmatching
candidate images are reported for provenance review; never assign them to dogs.
"""
import concurrent.futures as cf
import hashlib
from html.parser import HTMLParser
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

DOC=Path("docs/operations/MISSING_DOG_PHOTO_RECOVERY_2026-11-20.md")
OUT=Path("artifacts/cca-external-breeder-photo-check")
OUT.mkdir(parents=True,exist_ok=True)
SOURCES=[
 ("Kralj Custodi Nos","https://www.capefearcanecorso.com/single-post/karlj-custodi-nos",True),
 ("B-Aquila Clarissima Stella","https://www.imolossidelporto.co.uk/studs/",True),
 ("B-Aquila Clarissima Stella","https://www.pets4homes.co.uk/classifieds/y-xjfyemz-health-tested-fci-registered-gosport/",True),
 ("Ultimo Vidor Custodi Nos","https://pienlutidelcorso.com.br/filhote/Cane-Corso/22225",True),
 ("Sforza Deja Vue","https://delestanciokennel.com/en",False),
 ("Tabasco En Una Palabra","https://www.dogsfiles.com/index.php?breed=302&did=176556&ind=dogsbase&nlang=en&op=view",True),
 ("B-Zeus Clarissima Stella","https://canecorsopedigree.com/view_dog?id=119856",True),
 ("Oragorn Custodi Nos","https://canecorsopedigree.com/view_dog?id=120615",True),
 ("Don Simba","https://canecorsopedigree.com/view_dog?id=119534",True),
 ("Capri Linea Rossa","https://canecorsopedigree.com/view_dog?id=118503",True),
 ("Kralj Custodi Nos","https://www.capefearcanecorso.com/cape-fear-studs-1",False),
]
REQHEAD={"User-Agent":"Mozilla/5.0 (compatible; CaneCorsoAncestryPhotoRecovery/1.0)"}
def load(url,limit=8*1024*1024):
    with urlopen(Request(url,headers=REQHEAD),timeout=18) as response:
        content=response.read(limit+1)
        if len(content)>limit:raise ValueError("response exceeds safety limit")
        return content,dict(response.headers)
def targets():
    found=[]; dog=""
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):dog=line[4:].split(" (",1)[0]
        if not line.startswith("- "+chr(96)):continue
        key=line.split(chr(96),2)[1]
        if not key.startswith(("dogs/","submissions/")):continue
        if "— PRIMARY" not in line and "— gallery" not in line:continue
        match=re.search(r"[a-f0-9]{64}",line)
        found.append({"key":key,"dog":dog,"sha256":match.group() if match else ""})
    assert len(found)==48
    return found
class Gallery(HTMLParser):
    def __init__(self):
        super().__init__();self.images=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="img":
            alt=a.get("alt","") or ""
            for name in ("data-src","data-lazy-src","src","data-image","data-original"):
                if a.get(name):self.images.append((a[name],alt))
            if a.get("srcset"):
                items=a["srcset"].split(",")
                if items:self.images.append((items[-1].strip().split()[0],alt))
        if tag=="meta" and a.get("property") in ("og:image","twitter:image") and a.get("content"):
            self.images.append((a["content"],""))
def normalize(target,base):
    url=urljoin(base,target.strip())
    parsed=urlsplit(url)
    if parsed.scheme not in ("https","http") or not parsed.netloc:return None
    if any(z in parsed.netloc.lower() for z in ("facebook.com","doubleclick.net","google-analytics.com")):return None
    if not re.search(r"\.(jpg|jpeg|png|webp|avif)(?:$|[?/])",parsed.path,re.I):return None
    # Wix supplies a transformed URL; use the underlying original when possible.
    if "static.wixstatic.com" in parsed.netloc and "~mv2." in parsed.path:
        prefix=parsed.path.split("/v1/",1)[0]
        url="https://static.wixstatic.com"+prefix
    return url
def check_source(item):
    dog,page,dedicated=item
    try:
        payload,_=load(page,limit=6*1024*1024)
        parser=Gallery()
        parser.feed(payload.decode("utf-8","replace"))
        candidates=[];seen=set()
        for target,alt in parser.images:
            url=normalize(target,page)
            if not url or url in seen:continue
            seen.add(url)
            matched=dog.lower() in alt.lower() or dog.lower().replace("-"," ") in alt.lower().replace("-"," ")
            if not dedicated and not matched:continue
            score=10 if matched else 2
            if "wixstatic" in url:score+=1
            if re.search(r"(logo|banner|icon|privacy|health|award)",url,re.I):score-=5
            candidates.append({"url":url,"alt":alt[:160],"score":score})
        candidates.sort(key=lambda x:x["score"],reverse=True)
        return {"dog":dog,"page":page,"found":candidates[:40],"error":None}
    except Exception as e:
        return {"dog":dog,"page":page,"found":[],"error":str(type(e).__name__)+": "+str(e)[:150]}
def image_ok(data):
    return data.startswith((bytes.fromhex("ffd8ff"),bytes.fromhex("89504e470d0a1a0a"),b"GIF87a",b"GIF89a")) or data[:4]==b"RIFF" and data[8:12]==b"WEBP"
def compare(entry,expected):
    try:
        data,_=load(entry["url"],limit=12*1024*1024)
        if not image_ok(data) or len(data)<250:raise ValueError("not an image")
        digest=hashlib.sha256(data).hexdigest()
        matches=[t for t in expected if t["sha256"]==digest]
        item=dict(entry,sha256=digest,bytes=len(data),verified_keys=[t["key"] for t in matches],status="EXACT" if matches else "unverified")
        if matches:
            for t in matches:
                dest=OUT/"exact"/t["key"]
                dest.parent.mkdir(parents=True,exist_ok=True)
                if not dest.exists():dest.write_bytes(data)
        return item
    except Exception as e:
        return dict(entry,status="unavailable",error=str(type(e).__name__)+": "+str(e)[:130])
def main():
    expected=targets()
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        pages=list(pool.map(check_source,SOURCES))
    items=[]
    for page in pages:
        for c in page["found"][:35]:items.append((c,expected))
        print("SOURCE",page["dog"],"candidate image links",len(page["found"]),"error",page["error"],flush=True)
    # de-duplicate images downloaded across independent pages
    unique={c["url"]:(c,exp) for c,exp in items}
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        matched=list(pool.map(lambda x:compare(*x),unique.values()))
    exact=[x for x in matched if x["status"]=="EXACT"]
    available=[x for x in matched if x["status"]=="unverified"]
    report={"missing_originals":len(expected),"source_pages":pages,
            "unique_photo_urls_checked":len(matched),
            "exact_recovered":exact,
            "same_dog_external_candidates":[x for x in available if x["score"]>=10],
            "other_on_dedicated_pages":[x for x in available if x["score"]<10][:100],
            "failed_downloads":[x for x in matched if x["status"]=="unavailable"]}
    (OUT/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print("TOTAL SOURCES",len(SOURCES),"PUBLIC IMAGE URLS",len(matched),flush=True)
    print("EXACT ORIGINALS",len(exact),"NAMED-DOG CANDIDATES",len(report["same_dog_external_candidates"]),flush=True)
    print("No live website records modified; nonmatching images retained only by URL.",flush=True)
if __name__=="__main__":main()
