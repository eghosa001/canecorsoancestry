#!/usr/bin/env python3
"""R2 private encrypted backups, using the existing authenticated media gateway."""
import argparse,hashlib
from pathlib import Path
import django
django.setup()
from django.core.files.base import ContentFile
from core.r2_gateway_storage import CloudflareR2GatewayStorage
def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=("upload","download","delete"))
    p.add_argument("--key",required=True);p.add_argument("--file",required=True)
    a=p.parse_args()
    if (not a.key.startswith("private-cca-postgres-backups/v1/") or
        not (a.key.endswith(".sealed") or a.key.endswith("/latest.json")) or
        ".." in a.key):
        raise ValueError("Forbidden backup storage key")
    store=CloudflareR2GatewayStorage(timeout=50);path=Path(a.file)
    if a.mode=="delete":
        if a.key.endswith("/latest.json"):
            raise ValueError("Latest recovery pointer must not be deleted")
        store.delete(a.key)
        print("r2_expired_archive_deleted=true")
        return
    if a.mode=="upload":
        data=path.read_bytes()
        if a.key.endswith("/latest.json") and len(data)>4096:
            raise RuntimeError("Recovery pointer must be compact JSON")
        if len(data)>75*1024*1024: raise RuntimeError("Encrypted backup exceeds safe Worker transport limit")
        store.save_exact(a.key,ContentFile(data,name="postgres.sealed"))
        with store.open(a.key,"rb") as f:received=f.read()
        if hashlib.sha256(received).digest()!=hashlib.sha256(data).digest():
            raise RuntimeError("Remote R2 archive verification failed")
        print("r2_encrypted_archive_verified=true bytes="+str(len(data)))
    else:
        with store.open(a.key,"rb") as f:data=f.read()
        with path.open("xb") as f:f.write(data)
        path.chmod(0o600)
        print("r2_recovered_archive_sha256="+hashlib.sha256(data).hexdigest())
if __name__=="__main__":main()
