"""Durable state persistence to VNG vStorage (S3-compatible object storage).

A Custom Agent's filesystem is ephemeral and the runtime can't mount a volume
(verified: agent-runtimes have no volume field; the platform mandates statelessness).
So the durable subset is tarred and PUT to a vStorage bucket on each mutation, and
restored on boot. Runs are NOT persisted (regenerable). If the VSTORAGE_* env vars
are unset, every function is a no-op (local-only) — tests and local dev need no S3.
"""
from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path

from gaa.server import persona

STATE_KEY = "gaa-state.tar.gz"


def enabled() -> bool:
    return all(os.environ.get(k) for k in
               ("VSTORAGE_ENDPOINT", "VSTORAGE_BUCKET", "VSTORAGE_ACCESS_KEY", "VSTORAGE_SECRET_KEY"))


def _client():
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=os.environ["VSTORAGE_ENDPOINT"],
        aws_access_key_id=os.environ["VSTORAGE_ACCESS_KEY"],
        aws_secret_access_key=os.environ["VSTORAGE_SECRET_KEY"],
    )


def _durable_paths(ctx) -> list[Path]:
    """The files/dirs that must survive a redeploy (absolute paths)."""
    s = ctx.settings
    cache = Path(s.cache_dir)
    candidates = [
        Path(ctx.config._path),          # gaa-config.toml
        Path(s.db_path),                 # gaa.sqlite (profiles)
        cache / "metrics",               # parquet metrics
        Path(os.environ.get("GAA_TOOLS_DIR", str(cache / "tools"))),  # promoted tools
        persona.persona_dir(ctx),        # SOUL.md + MEMORY.md
    ]
    return [p for p in candidates if p.exists()]


def snapshot(ctx, *, client=None, bucket: str | None = None) -> bool:
    """Tar the durable subset and PUT it. Returns False (no-op) if disabled."""
    if client is None:
        if not enabled():
            return False
        client = _client()
    bucket = bucket or os.environ.get("VSTORAGE_BUCKET")
    root = os.path.dirname(os.path.abspath(ctx.settings.cache_dir)) or "/"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in _durable_paths(ctx):
            arcname = os.path.relpath(str(p), root)
            if arcname.startswith(".."):
                # Path is outside the snapshot root (e.g. GAA_TOOLS_DIR set to a
                # foreign directory); skip it — it would fail extractall's filter.
                continue
            tar.add(str(p), arcname=arcname)
    client.put_object(Bucket=bucket, Key=STATE_KEY, Body=buf.getvalue())
    return True


def restore(ctx, *, client=None, bucket: str | None = None) -> bool:
    """Pull the latest snapshot and extract it. Returns False if disabled or none exists."""
    if client is None:
        if not enabled():
            return False
        client = _client()
    bucket = bucket or os.environ.get("VSTORAGE_BUCKET")
    try:
        obj = client.get_object(Bucket=bucket, Key=STATE_KEY)
    except Exception:  # NoSuchKey / first boot
        return False
    data = obj["Body"].read()
    root = os.path.dirname(os.path.abspath(ctx.settings.cache_dir)) or "/"
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        tar.extractall(root, filter="data")
    return True
