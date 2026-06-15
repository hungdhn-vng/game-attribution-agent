"""Durable state persistence to VNG vStorage (S3-compatible object storage).

A Custom Agent's filesystem is ephemeral and the runtime can't mount a volume, so the
durable subset is tarred and PUT to a vStorage bucket on each mutation, and restored on
boot. Each durable item is stored under a FIXED logical arcname (independent of its
on-disk path), so the snapshot round-trips correctly regardless of how GAA_CACHE_DIR /
GAA_DB_PATH / GAA_CONFIG_PATH are laid out. Runs are NOT persisted (regenerable). If the
VSTORAGE_* env vars are unset, every function is a no-op (local-only) — tests and local
dev need no S3.
"""
from __future__ import annotations

import io
import os
import shutil
import tarfile
import tempfile
from pathlib import Path


STATE_KEY = "gaa-state.tar.gz"


def enabled() -> bool:
    return all(os.environ.get(k) for k in
               ("VSTORAGE_ENDPOINT", "VSTORAGE_BUCKET", "VSTORAGE_ACCESS_KEY", "VSTORAGE_SECRET_KEY"))


def _client():
    """boto3 S3 client tuned for VNG vStorage (Ceph-based, S3-compatible).

    - path-style addressing + SigV4 (vStorage doesn't do virtual-host buckets).
    - request/response checksum = "when_required": boto3 >=1.36 defaults uploads to
      CRC64_NVME, which vStorage rejects (it supports only CRC32/CRC32C/SHA1/SHA256);
      "when_required" suppresses that default so put_object succeeds. Falls back
      gracefully on older botocore that lacks the knobs.
    - region is configurable (VSTORAGE_REGION); only used for signing.
    """
    import boto3
    from botocore.config import Config

    base = dict(signature_version="s3v4", s3={"addressing_style": "path"})
    try:
        cfg = Config(**base, request_checksum_calculation="when_required",
                     response_checksum_validation="when_required")
    except TypeError:  # botocore < 1.36 has no checksum knobs
        cfg = Config(**base)
    return boto3.client(
        "s3",
        endpoint_url=os.environ["VSTORAGE_ENDPOINT"],
        region_name=os.environ.get("VSTORAGE_REGION", "us-east-1"),
        aws_access_key_id=os.environ["VSTORAGE_ACCESS_KEY"],
        aws_secret_access_key=os.environ["VSTORAGE_SECRET_KEY"],
        config=cfg,
    )


def _durable_items(ctx):
    """(arcname, absolute on-disk path, is_dir) for each durable item.

    arcname is a FIXED logical name, so the snapshot is independent of the host layout
    (cache dir, db path, and config path can live anywhere).
    """
    cache = Path(ctx.settings.cache_dir)
    tools = Path(os.environ.get("GAA_TOOLS_DIR", str(cache / "tools")))
    openclaw_home = Path(os.environ.get("OPENCLAW_HOME", str(Path.home() / ".openclaw")))
    return [
        ("config.toml", Path(ctx.config._path), False),
        ("profiles.sqlite", Path(ctx.settings.db_path), False),
        ("metrics", cache / "metrics", True),
        ("tools", tools, True),
        ("openclaw_workspace", openclaw_home / "workspace", True),
    ]


def snapshot(ctx, *, client=None, bucket=None) -> bool:
    """Tar the durable subset under fixed arcnames and PUT it. No-op (False) if disabled."""
    if client is None:
        if not enabled():
            return False
        client = _client()
    bucket = bucket or os.environ.get("VSTORAGE_BUCKET")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for arcname, path, _is_dir in _durable_items(ctx):
            if path.exists():
                tar.add(str(path), arcname=arcname)
    client.put_object(Bucket=bucket, Key=STATE_KEY, Body=buf.getvalue())
    return True


def restore(ctx, *, client=None, bucket=None) -> bool:
    """Pull the latest snapshot and place each item at its on-disk destination.

    Returns False if disabled or no snapshot exists; re-raises real S3 errors.
    """
    if client is None:
        if not enabled():
            return False
        client = _client()
    bucket = bucket or os.environ.get("VSTORAGE_BUCKET")
    from botocore.exceptions import ClientError
    try:
        obj = client.get_object(Bucket=bucket, Key=STATE_KEY)
    except ClientError as exc:  # missing key/bucket = first boot; anything else is a real error
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "NoSuchBucket", "404"):
            return False
        raise
    data = obj["Body"].read()
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            try:
                tar.extractall(tmp, filter="data")
            except TypeError:
                # Python < 3.11.4 (e.g. Debian bookworm's 3.11.2) lacks the PEP 706
                # `filter` kwarg. The snapshot tarball is self-produced and trusted,
                # so extracting without the data filter is safe here.
                tar.extractall(tmp)
        for arcname, dest, _is_dir in _durable_items(ctx):
            src = Path(tmp) / arcname
            if not src.exists():
                continue
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            shutil.move(str(src), str(dest))
    return True


def _main(argv=None) -> int:
    import sys
    from gaa.cli.wiring import build_context
    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else "restore"
    try:
        ctx = build_context()
        if cmd == "restore":
            print(f"persist.restore: {restore(ctx)}")
        elif cmd == "snapshot":
            print(f"persist.snapshot: {snapshot(ctx)}")
        else:
            print(f"unknown persist command: {cmd!r}", file=sys.stderr)
            return 2
    except Exception as exc:  # never block container boot on a restore error
        print(f"persist {cmd} error (continuing): {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
