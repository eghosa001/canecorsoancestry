#!/usr/bin/env python3
"""Encrypted+authenticated pg_dump backup; 256-bit AES-CBC PBKDF2 + HMAC-SHA256."""
import argparse,hashlib,hmac,os,subprocess
from pathlib import Path
MAGIC=b"CCA-PG-BACKUP-V1\n"
def getkey(path):
    entries=[v.split("=",1)[1] for v in Path(path).read_text().splitlines() if v.startswith("DJANGO_SECRET_KEY=")]
    if len(entries)!=1 or len(entries[0])<24: raise ValueError("Missing secret")
    return entries[0].encode()
def run(data, password, decrypt):
    cmd=["openssl","enc","-aes-256-cbc","-pbkdf2","-iter","200000","-pass","env:CCA_PG_KEY"]
    if decrypt: cmd.append("-d")
    env={"PATH":os.getenv("PATH","/usr/bin:/bin"),"CCA_PG_KEY":password}
    r=subprocess.run(cmd,input=data,capture_output=True,env=env)
    if r.returncode: raise RuntimeError("Encrypted archive transformation failed")
    return r.stdout
def process(mode,source,output,key):
    enc=hmac.new(key,b"cca-backup-encryption-v1",hashlib.sha256).hexdigest()
    auth=hmac.new(key,b"cca-backup-integrity-v1",hashlib.sha256).digest()
    data=Path(source).read_bytes()
    if mode=="seal":
        ciphertext=run(data,enc,False)
        data=MAGIC+hmac.new(auth,MAGIC+ciphertext,hashlib.sha256).digest()+ciphertext
    else:
        if not data.startswith(MAGIC) or len(data)<=len(MAGIC)+32: raise RuntimeError("Invalid backup header")
        tag=data[len(MAGIC):len(MAGIC)+32];ciphertext=data[len(MAGIC)+32:]
        valid=hmac.new(auth,MAGIC+ciphertext,hashlib.sha256).digest()
        if not hmac.compare_digest(tag,valid): raise RuntimeError("Backup integrity verification failed")
        data=run(ciphertext,enc,True)
    fd=os.open(output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,"wb") as f:f.write(data)
    except BaseException:
        Path(output).unlink(missing_ok=True);raise
    print("backup_crypto="+mode+" bytes="+str(len(data))+" sha256="+hashlib.sha256(data).hexdigest(),flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=("seal","open"))
    p.add_argument("source");p.add_argument("output");p.add_argument("--secret-env",required=True)
    a=p.parse_args()
    process(a.mode,a.source,a.output,getkey(a.secret_env))
