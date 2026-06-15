import io
import tarfile
import os
from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa import persist


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
    monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path / ".openclaw"))
    ctx = _ctx(tmp_path, monkeypatch)
    # seed the openclaw workspace (only the workspace subdir is snapshotted now)
    openclaw_dir = tmp_path / ".openclaw"
    workspace_dir = openclaw_dir / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "MEMORY.md").write_text("# MEMORY\n\nLearned: ShooterX is hot.\n")
    ctx.config.set("benchmark_mode", "crawl")  # writes gaa-config.toml

    s3 = FakeS3()
    assert persist.snapshot(ctx, client=s3, bucket="b") is True
    assert ("b", persist.STATE_KEY) in s3.objects

    # wipe local openclaw workspace + config, then restore from the snapshot
    import shutil
    shutil.rmtree(workspace_dir)
    os.remove(ctx.config._path) if os.path.exists(ctx.config._path) else None

    assert persist.restore(ctx, client=s3, bucket="b") is True
    # restore places the workspace dir at <OPENCLAW_HOME>/workspace
    assert "ShooterX" in (workspace_dir / "MEMORY.md").read_text()


def test_snapshot_uses_workspace_arcname_not_openclaw_root(tmp_path, monkeypatch):
    """Snapshot must use 'openclaw_workspace' arcname (not 'openclaw') so openclaw.json
    is NOT captured and the workspace lands at <OPENCLAW_HOME>/workspace on restore."""
    monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path / ".openclaw"))
    ctx = _ctx(tmp_path, monkeypatch)
    workspace_dir = tmp_path / ".openclaw" / "workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "SOUL.md").write_text("# SOUL\n")
    # also place openclaw.json in the root (should NOT be snapshotted)
    (tmp_path / ".openclaw" / "openclaw.json").write_text("{}")

    s3 = FakeS3()
    persist.snapshot(ctx, client=s3, bucket="b")
    names = tarfile.open(fileobj=io.BytesIO(s3.objects[("b", persist.STATE_KEY)]), mode="r:gz").getnames()
    # workspace is included
    assert any(n == "openclaw_workspace" or n.startswith("openclaw_workspace/") for n in names)
    # root dir and openclaw.json are NOT included
    assert "openclaw" not in names
    assert not any(n == "openclaw/openclaw.json" for n in names)


def test_restore_noop_when_no_snapshot(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    s3 = FakeS3()
    assert persist.restore(ctx, client=s3, bucket="b") is False


def test_roundtrip_persists_config_and_db_under_production_layout(tmp_path, monkeypatch):
    # Production layout: cache_dir is BELOW the db/config (one level deeper). The old
    # relpath-based root skipped gaa.sqlite + gaa-config.toml; they MUST round-trip.
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "data" / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    ctx = build_context(llm=FakeLLM({}), today="2026-06-13")
    ctx.config.set("benchmark_mode", "crawl")  # writes gaa-config.toml
    from gaa.core.schema.profile import GameProfile, ColumnMapping
    ctx.profiles.save(GameProfile(name="ShooterX", platform="roblox", genre="shooter",
                                  mapping=ColumnMapping(date_col="d", metric_cols={"dau": "dau"})))

    s3 = FakeS3()
    assert persist.snapshot(ctx, client=s3, bucket="b") is True
    # the tar must actually contain the config + db (the bug skipped them)
    import io as _io, tarfile as _tf
    names = _tf.open(fileobj=_io.BytesIO(s3.objects[("b", persist.STATE_KEY)]), mode="r:gz").getnames()
    assert "config.toml" in names
    assert "profiles.sqlite" in names

    # mutate config + wipe the db, then restore must bring both back
    ctx.config.set("benchmark_mode", "snapshot")
    os.remove(ctx.settings.db_path)
    assert persist.restore(ctx, client=s3, bucket="b") is True

    ctx2 = build_context(llm=FakeLLM({}), today="2026-06-13")
    assert ctx2.config.resolve("benchmark_mode")[0] == "crawl"
    assert "ShooterX" in ctx2.profiles.list_names()


def test_client_is_tuned_for_vstorage(monkeypatch):
    # _client() builds a boto3 S3 client (no network) with path-style addressing +
    # the vStorage endpoint, so put_object/get_object work against Ceph-based vStorage.
    monkeypatch.setenv("VSTORAGE_ENDPOINT", "https://hcm04.vstorage.vngcloud.vn")
    monkeypatch.setenv("VSTORAGE_BUCKET", "b")
    monkeypatch.setenv("VSTORAGE_ACCESS_KEY", "ak")
    monkeypatch.setenv("VSTORAGE_SECRET_KEY", "sk")
    monkeypatch.setenv("VSTORAGE_REGION", "hcm04")
    c = persist._client()
    assert c.meta.endpoint_url == "https://hcm04.vstorage.vngcloud.vn"
    assert c.meta.config.s3["addressing_style"] == "path"
    assert c.meta.config.signature_version == "s3v4"
    assert c.meta.region_name == "hcm04"
