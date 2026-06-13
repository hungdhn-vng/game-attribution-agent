import io
import tarfile
import os
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa import persist
from gaa.server import persona


class FakeS3:
    """In-memory stand-in for a boto3 S3 client (only the methods persist.py uses)."""
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body if isinstance(Body, bytes) else Body.read()

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


def _ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    return build_context(llm=FakeLLM({}), today="2026-06-13")


def test_enabled_false_without_env(tmp_path, monkeypatch):
    for k in ("VSTORAGE_ENDPOINT", "VSTORAGE_BUCKET", "VSTORAGE_ACCESS_KEY", "VSTORAGE_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert persist.enabled() is False


def test_snapshot_noop_when_disabled(tmp_path, monkeypatch):
    for k in ("VSTORAGE_ENDPOINT", "VSTORAGE_BUCKET", "VSTORAGE_ACCESS_KEY", "VSTORAGE_SECRET_KEY"):
        monkeypatch.delenv(k, raising=False)
    ctx = _ctx(tmp_path, monkeypatch)
    # disabled -> returns False, does not raise
    assert persist.snapshot(ctx, client=None) is False


def test_snapshot_then_restore_roundtrip(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    persona.ensure_seeded(ctx)
    persona.write_persona(ctx, "MEMORY.md", "# MEMORY\n\nLearned: ShooterX is hot.\n")
    ctx.config.set("benchmark_mode", "crawl")  # writes gaa-config.toml

    s3 = FakeS3()
    assert persist.snapshot(ctx, client=s3, bucket="b") is True
    assert ("b", persist.STATE_KEY) in s3.objects

    # wipe local persona + config, then restore from the snapshot
    (persona.persona_dir(ctx) / "MEMORY.md").unlink()
    os.remove(ctx.config._path) if os.path.exists(ctx.config._path) else None

    assert persist.restore(ctx, client=s3, bucket="b") is True
    assert "ShooterX" in persona.load_memory(ctx)


def test_restore_noop_when_no_snapshot(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    s3 = FakeS3()
    assert persist.restore(ctx, client=s3, bucket="b") is False
