import hashlib
import hmac


def body_sha256(data):
    return hashlib.sha256(data).hexdigest()


def migration_signature(secret, timestamp, path, digest):
    message = f"{timestamp}\n{path}\n{digest}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def valid_migration_signature(secret, timestamp, path, digest, provided):
    expected = migration_signature(secret, timestamp, path, digest)
    return hmac.compare_digest(expected, provided or "")
