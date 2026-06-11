# Game Attribution Agent — Plan 1: Foundations & Data Layer

> ⚠️ **RECONCILED BY [Plan 0 — AgentBase + LangGraph Integration](2026-06-11-game-attribution-agent-plan-0-agentbase-langgraph-integration.md).** This plan's **pure-logic tasks (2–6: canonical schema, ColumnMapping/GameProfile, CSV+Roblox adapters, ProfileStore) remain valid as written.** **Superseded:** Task 0 (skeleton → AgentBase scaffold), Task 1 (config → MaaS `LLM_*` env vars), Tasks 7–9 (FastAPI app + generic Dockerfile + generic deploy → SDK `main.py` + scaffold Dockerfile + `/agentbase-deploy`). Build on the `src/gaa` layout with a root `main.py`. See Plan 0's supersession map before executing.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a deployable FastAPI service that ingests game metrics (generic CSV + Roblox export) into a single canonical schema and persists a per-game `GameProfile`, with a hello-world container running on AgentBase.

**Architecture:** A `src/gaa` Python package. Raw platform data passes through an `Adapter` that normalizes it into a long-format **canonical metrics DataFrame** (`date, metric, value` + dimension columns). A `ColumnMapping` describes how a team's columns map to canonical fields; a `GameProfile` (name, platform, genre, mapping, external config) is persisted in sqlite via `ProfileStore`. A thin FastAPI app exposes `/health`, profile CRUD, and a stub `/analyze` (implemented in Plan 2). All units are independently unit-tested; the analysis engine (Plan 2) and renderer/onboarding (Plan 3) build on these contracts.

**Tech Stack:** Python 3.11, FastAPI + uvicorn, Pydantic v2, pandas, duckdb, sqlite (stdlib), pytest, Docker.

**Scope note:** This plan is the data foundation only. The orchestrator, analysis modules, Evidence Ledger, synthesizer, charts, and chat-assisted onboarding are Plans 2 & 3. Where a Plan 2/3 contract is referenced, the exact type signature is given so this plan stays self-contained.

---

### Task 0: Repository skeleton, tooling, and git

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `src/gaa/__init__.py`
- Create: `tests/__init__.py`
- Create: `README.md`

- [ ] **Step 1: Initialize git**

Run:
```bash
cd /Users/lap16006/Documents/Projects/TestGreenNode
git init
git branch -m main
```
Expected: "Initialized empty Git repository".

- [ ] **Step 2: Create `requirements.txt`**

```
fastapi==0.115.*
uvicorn[standard]==0.30.*
pydantic==2.*
pandas==2.*
duckdb==1.*
plotly==5.*
jinja2==3.*
httpx==0.27.*
beautifulsoup4==4.*
anthropic==0.39.*
pytest==8.*
```

- [ ] **Step 3: Create `pyproject.toml`**

```toml
[project]
name = "gaa"
version = "0.1.0"
requires-python = ">=3.11"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 4: Create `.gitignore`**

```
__pycache__/
*.pyc
.venv/
*.sqlite
*.sqlite3
.env
.pytest_cache/
data/cache/
```

- [ ] **Step 5: Create empty package files and a stub README**

`src/gaa/__init__.py`:
```python
__version__ = "0.1.0"
```
`tests/__init__.py`: (empty file)
`README.md`:
```markdown
# Game Attribution Agent
AI agent that reconstructs the story behind a game's metric movement,
separating internal vs market causes, with dual-axis confidence and cited evidence.
GreenNode Claw-a-thon 2026 — Data Analysis track.
```

- [ ] **Step 6: Create venv and install**

Run:
```bash
python3.11 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && pip install -e .
```
Expected: installs complete, no errors.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: project skeleton, deps, tooling"
```

---

### Task 1: Config

**Files:**
- Create: `src/gaa/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
from gaa.config import Settings

def test_defaults_present(monkeypatch):
    monkeypatch.delenv("GAA_MODEL", raising=False)
    s = Settings()
    assert s.model == "claude-haiku-4-5-20251001"
    assert s.maas_fallback_model == "qwen-3-27b"
    assert s.db_path.endswith(".sqlite")

def test_env_override(monkeypatch):
    monkeypatch.setenv("GAA_MODEL", "claude-sonnet-4-6")
    assert Settings().model == "claude-sonnet-4-6"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gaa.config'`.

- [ ] **Step 3: Write minimal implementation**

`src/gaa/config.py`:
```python
import os
from dataclasses import dataclass, field


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


@dataclass
class Settings:
    model: str = field(default_factory=lambda: _env("GAA_MODEL", "claude-haiku-4-5-20251001"))
    maas_fallback_model: str = field(default_factory=lambda: _env("GAA_MAAS_MODEL", "qwen-3-27b"))
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY", ""))
    maas_base_url: str = field(default_factory=lambda: _env("GAA_MAAS_BASE_URL", ""))
    db_path: str = field(default_factory=lambda: _env("GAA_DB_PATH", "gaa.sqlite"))
    cache_dir: str = field(default_factory=lambda: _env("GAA_CACHE_DIR", "data/cache"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/config.py tests/test_config.py
git commit -m "feat: settings/config with env overrides"
```

---

### Task 2: Canonical metrics schema

**Files:**
- Create: `src/gaa/schema/__init__.py` (empty)
- Create: `src/gaa/schema/canonical.py`
- Test: `tests/schema/test_canonical.py`
- Create: `tests/schema/__init__.py` (empty)

The canonical form is a **long-format** pandas DataFrame: one row per (date, metric, dimension-combination). Required columns `date, metric, value`; optional dimension columns are nullable.

- [ ] **Step 1: Write the failing test**

`tests/schema/test_canonical.py`:
```python
import pandas as pd
import pytest
from gaa.schema.canonical import (
    CANONICAL_DIMS, REQUIRED_COLUMNS, validate_canonical, empty_canonical,
)

def test_constants():
    assert REQUIRED_COLUMNS == ["date", "metric", "value"]
    assert "region" in CANONICAL_DIMS and "version" in CANONICAL_DIMS

def test_empty_has_all_columns():
    df = empty_canonical()
    for c in REQUIRED_COLUMNS + CANONICAL_DIMS:
        assert c in df.columns

def test_validate_accepts_good_frame():
    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-05-01", "2026-05-02"]),
        "metric": ["dau", "dau"],
        "value": [100.0, 90.0],
    })
    out = validate_canonical(df)
    assert list(out["metric"]) == ["dau", "dau"]
    assert "region" in out.columns  # missing dims backfilled

def test_validate_rejects_missing_required():
    df = pd.DataFrame({"metric": ["dau"], "value": [1.0]})
    with pytest.raises(ValueError, match="date"):
        validate_canonical(df)

def test_validate_coerces_types():
    df = pd.DataFrame({"date": ["2026-05-01"], "metric": ["dau"], "value": ["100"]})
    out = validate_canonical(df)
    assert pd.api.types.is_datetime64_any_dtype(out["date"])
    assert out["value"].dtype == float
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/schema/test_canonical.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gaa.schema.canonical'`.

- [ ] **Step 3: Write minimal implementation**

`src/gaa/schema/canonical.py`:
```python
import pandas as pd

REQUIRED_COLUMNS = ["date", "metric", "value"]
CANONICAL_DIMS = ["platform", "region", "version", "cohort", "device", "source"]
ALL_COLUMNS = REQUIRED_COLUMNS + CANONICAL_DIMS


def empty_canonical() -> pd.DataFrame:
    return pd.DataFrame(columns=ALL_COLUMNS)


def validate_canonical(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"canonical frame missing required columns: {missing}")
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="raise")
    out["value"] = out["value"].astype(float)
    out["metric"] = out["metric"].astype(str)
    for dim in CANONICAL_DIMS:
        if dim not in out.columns:
            out[dim] = None
    return out[ALL_COLUMNS]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/schema/test_canonical.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/schema/ tests/schema/
git commit -m "feat: canonical metrics schema + validation"
```

---

### Task 3: ColumnMapping + GameProfile models

**Files:**
- Create: `src/gaa/schema/profile.py`
- Test: `tests/schema/test_profile.py`

- [ ] **Step 1: Write the failing test**

`tests/schema/test_profile.py`:
```python
from gaa.schema.profile import ColumnMapping, GameProfile

def test_column_mapping_roundtrip():
    m = ColumnMapping(
        date_col="dt",
        metric_cols={"dau_count": "dau", "rev": "revenue"},
        dim_cols={"country": "region", "app_version": "version"},
    )
    assert m.metric_cols["dau_count"] == "dau"
    assert ColumnMapping(**m.model_dump()) == m

def test_game_profile_defaults():
    p = GameProfile(
        name="MyGame",
        platform="roblox",
        genre="survival",
        mapping=ColumnMapping(date_col="dt", metric_cols={"dau_count": "dau"}, dim_cols={}),
    )
    assert p.external_source_config == {}
    assert p.created_at  # auto-stamped ISO string
    assert GameProfile(**p.model_dump()).name == "MyGame"

def test_mapping_rejects_unknown_canonical_metric_field():
    import pytest
    with pytest.raises(ValueError):
        ColumnMapping(date_col="dt", metric_cols={"x": ""}, dim_cols={})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/schema/test_profile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gaa.schema.profile'`.

- [ ] **Step 3: Write minimal implementation**

`src/gaa/schema/profile.py`:
```python
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator


class ColumnMapping(BaseModel):
    date_col: str
    metric_cols: dict[str, str]  # source_col -> canonical metric name (e.g. "dau")
    dim_cols: dict[str, str] = {}  # source_col -> canonical dim name

    @field_validator("metric_cols")
    @classmethod
    def _non_empty_metric_names(cls, v: dict[str, str]) -> dict[str, str]:
        for src, canon in v.items():
            if not canon:
                raise ValueError(f"empty canonical metric name for column '{src}'")
        return v


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GameProfile(BaseModel):
    name: str
    platform: str
    genre: str
    mapping: ColumnMapping
    external_source_config: dict = {}
    created_at: str = Field(default_factory=_now_iso)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/schema/test_profile.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/schema/profile.py tests/schema/test_profile.py
git commit -m "feat: ColumnMapping + GameProfile models"
```

---

### Task 4: Adapter base + Generic CSV adapter

**Files:**
- Create: `src/gaa/adapters/__init__.py` (empty)
- Create: `src/gaa/adapters/base.py`
- Create: `src/gaa/adapters/csv_adapter.py`
- Create: `src/gaa/data/sample/generic_metrics.csv`
- Test: `tests/adapters/test_csv_adapter.py`
- Create: `tests/adapters/__init__.py` (empty)

The CSV adapter melts a **wide** CSV (one column per metric) into the canonical long format using a `ColumnMapping`.

- [ ] **Step 1: Create the sample fixture**

`src/gaa/data/sample/generic_metrics.csv`:
```csv
dt,dau_count,rev,country,app_version
2026-05-01,1000,500.0,SEA,3.1
2026-05-02,950,480.0,SEA,3.1
2026-05-03,600,300.0,SEA,3.2
2026-05-01,800,400.0,NA,3.1
2026-05-02,790,395.0,NA,3.1
2026-05-03,770,380.0,NA,3.2
```

- [ ] **Step 2: Write the failing test**

`tests/adapters/test_csv_adapter.py`:
```python
from pathlib import Path
import pandas as pd
from gaa.adapters.csv_adapter import CSVAdapter
from gaa.schema.profile import ColumnMapping

SAMPLE = Path("src/gaa/data/sample/generic_metrics.csv")

def _mapping():
    return ColumnMapping(
        date_col="dt",
        metric_cols={"dau_count": "dau", "rev": "revenue"},
        dim_cols={"country": "region", "app_version": "version"},
    )

def test_melts_wide_to_canonical_long():
    df = CSVAdapter().load(str(SAMPLE), _mapping())
    # 6 rows x 2 metrics = 12 canonical rows
    assert len(df) == 12
    assert set(df["metric"].unique()) == {"dau", "revenue"}
    assert {"region", "version"}.issubset(df.columns)

def test_values_and_dims_preserved():
    df = CSVAdapter().load(str(SAMPLE), _mapping())
    row = df[(df["metric"] == "dau") & (df["region"] == "SEA") &
             (df["date"] == pd.Timestamp("2026-05-03"))]
    assert len(row) == 1
    assert row.iloc[0]["value"] == 600.0
    assert row.iloc[0]["version"] == "3.2"

def test_accepts_dataframe_input():
    raw = pd.read_csv(SAMPLE)
    df = CSVAdapter().load(raw, _mapping())
    assert len(df) == 12
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/adapters/test_csv_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gaa.adapters.csv_adapter'`.

- [ ] **Step 4: Write the base protocol**

`src/gaa/adapters/base.py`:
```python
from typing import Protocol, Union
import pandas as pd
from gaa.schema.profile import ColumnMapping


class Adapter(Protocol):
    def load(self, raw: Union[str, pd.DataFrame], mapping: ColumnMapping) -> pd.DataFrame:
        """Return a validated canonical long-format DataFrame."""
        ...
```

- [ ] **Step 5: Write the CSV adapter**

`src/gaa/adapters/csv_adapter.py`:
```python
from typing import Union
import pandas as pd
from gaa.schema.profile import ColumnMapping
from gaa.schema.canonical import validate_canonical


class CSVAdapter:
    def load(self, raw: Union[str, pd.DataFrame], mapping: ColumnMapping) -> pd.DataFrame:
        raw_df = raw if isinstance(raw, pd.DataFrame) else pd.read_csv(raw)
        id_vars = [mapping.date_col] + list(mapping.dim_cols.keys())
        value_vars = list(mapping.metric_cols.keys())
        long = raw_df.melt(
            id_vars=id_vars, value_vars=value_vars,
            var_name="_src_metric", value_name="value",
        )
        long["metric"] = long["_src_metric"].map(mapping.metric_cols)
        long = long.rename(columns={mapping.date_col: "date", **mapping.dim_cols})
        long = long.drop(columns=["_src_metric"])
        return validate_canonical(long)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/adapters/test_csv_adapter.py -v`
Expected: PASS (3 passed).

- [ ] **Step 7: Commit**

```bash
git add src/gaa/adapters/ src/gaa/data/sample/generic_metrics.csv tests/adapters/
git commit -m "feat: adapter protocol + generic CSV adapter (wide->canonical)"
```

---

### Task 5: Roblox adapter

**Files:**
- Create: `src/gaa/adapters/roblox_adapter.py`
- Create: `src/gaa/data/sample/roblox_export.csv`
- Test: `tests/adapters/test_roblox_adapter.py`

The Roblox adapter wraps `CSVAdapter` with a default mapping for known Creator Dashboard export columns, and lets callers override.

- [ ] **Step 1: Create the sample Roblox export fixture**

`src/gaa/data/sample/roblox_export.csv`:
```csv
Date,DAU,D1 Retention,D7 Retention,Revenue,Platform,Country
2026-05-01,12000,0.42,0.18,2400,Mobile,SEA
2026-05-02,11800,0.41,0.17,2380,Mobile,SEA
2026-05-03,9000,0.30,0.11,1500,Mobile,SEA
2026-05-01,4000,0.40,0.19,900,PC,NA
2026-05-02,3950,0.40,0.18,890,PC,NA
2026-05-03,3800,0.39,0.17,860,PC,NA
```

- [ ] **Step 2: Write the failing test**

`tests/adapters/test_roblox_adapter.py`:
```python
from pathlib import Path
import pandas as pd
from gaa.adapters.roblox_adapter import RobloxAdapter, DEFAULT_ROBLOX_MAPPING

SAMPLE = Path("src/gaa/data/sample/roblox_export.csv")

def test_default_mapping_covers_core_metrics():
    canon_metrics = set(DEFAULT_ROBLOX_MAPPING.metric_cols.values())
    assert {"dau", "retention_d1", "retention_d7", "revenue"} <= canon_metrics

def test_loads_with_default_mapping():
    df = RobloxAdapter().load(str(SAMPLE))
    assert set(df["metric"].unique()) >= {"dau", "retention_d7", "revenue"}
    row = df[(df["metric"] == "dau") & (df["platform"] == "Mobile") &
             (df["date"] == pd.Timestamp("2026-05-03"))]
    assert row.iloc[0]["value"] == 9000.0

def test_load_accepts_override_mapping():
    from gaa.schema.profile import ColumnMapping
    m = ColumnMapping(date_col="Date", metric_cols={"DAU": "dau"}, dim_cols={"Country": "region"})
    df = RobloxAdapter().load(str(SAMPLE), m)
    assert set(df["metric"].unique()) == {"dau"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/adapters/test_roblox_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gaa.adapters.roblox_adapter'`.

- [ ] **Step 4: Write the implementation**

`src/gaa/adapters/roblox_adapter.py`:
```python
from typing import Optional, Union
import pandas as pd
from gaa.adapters.csv_adapter import CSVAdapter
from gaa.schema.profile import ColumnMapping

DEFAULT_ROBLOX_MAPPING = ColumnMapping(
    date_col="Date",
    metric_cols={
        "DAU": "dau",
        "D1 Retention": "retention_d1",
        "D7 Retention": "retention_d7",
        "Revenue": "revenue",
    },
    dim_cols={"Platform": "platform", "Country": "region"},
)


class RobloxAdapter:
    def __init__(self) -> None:
        self._csv = CSVAdapter()

    def load(self, raw: Union[str, pd.DataFrame],
             mapping: Optional[ColumnMapping] = None) -> pd.DataFrame:
        return self._csv.load(raw, mapping or DEFAULT_ROBLOX_MAPPING)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/adapters/test_roblox_adapter.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add src/gaa/adapters/roblox_adapter.py src/gaa/data/sample/roblox_export.csv tests/adapters/test_roblox_adapter.py
git commit -m "feat: roblox adapter with default dashboard-export mapping"
```

---

### Task 6: ProfileStore (sqlite persistence)

**Files:**
- Create: `src/gaa/store/__init__.py` (empty)
- Create: `src/gaa/store/profile_store.py`
- Test: `tests/store/test_profile_store.py`
- Create: `tests/store/__init__.py` (empty)

- [ ] **Step 1: Write the failing test**

`tests/store/test_profile_store.py`:
```python
from gaa.store.profile_store import ProfileStore
from gaa.schema.profile import GameProfile, ColumnMapping

def _profile(name="MyGame"):
    return GameProfile(
        name=name, platform="roblox", genre="survival",
        mapping=ColumnMapping(date_col="Date", metric_cols={"DAU": "dau"}, dim_cols={}),
    )

def test_save_and_get(tmp_path):
    store = ProfileStore(str(tmp_path / "t.sqlite"))
    store.save(_profile())
    got = store.get("MyGame")
    assert got is not None and got.name == "MyGame"
    assert got.mapping.metric_cols == {"DAU": "dau"}

def test_get_missing_returns_none(tmp_path):
    store = ProfileStore(str(tmp_path / "t.sqlite"))
    assert store.get("nope") is None

def test_active_profile_tracking(tmp_path):
    store = ProfileStore(str(tmp_path / "t.sqlite"))
    store.save(_profile("A"))
    store.save(_profile("B"))
    store.set_active("B")
    assert store.get_active().name == "B"
    assert sorted(store.list_names()) == ["A", "B"]

def test_save_overwrites_same_name(tmp_path):
    store = ProfileStore(str(tmp_path / "t.sqlite"))
    store.save(_profile())
    p2 = _profile()
    p2.genre = "rpg"
    store.save(p2)
    assert store.get("MyGame").genre == "rpg"
    assert store.list_names() == ["MyGame"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/store/test_profile_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gaa.store.profile_store'`.

- [ ] **Step 3: Write minimal implementation**

`src/gaa/store/profile_store.py`:
```python
import sqlite3
from typing import Optional
from gaa.schema.profile import GameProfile


class ProfileStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        with self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS profiles "
                "(name TEXT PRIMARY KEY, json TEXT NOT NULL)"
            )
            c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def save(self, profile: GameProfile) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO profiles(name, json) VALUES(?, ?) "
                "ON CONFLICT(name) DO UPDATE SET json=excluded.json",
                (profile.name, profile.model_dump_json()),
            )

    def get(self, name: str) -> Optional[GameProfile]:
        with self._conn() as c:
            row = c.execute("SELECT json FROM profiles WHERE name=?", (name,)).fetchone()
        return GameProfile.model_validate_json(row[0]) if row else None

    def list_names(self) -> list[str]:
        with self._conn() as c:
            return [r[0] for r in c.execute("SELECT name FROM profiles ORDER BY name")]

    def set_active(self, name: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO meta(key, value) VALUES('active', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (name,),
            )

    def get_active(self) -> Optional[GameProfile]:
        with self._conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key='active'").fetchone()
        return self.get(row[0]) if row else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/store/test_profile_store.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/store/ tests/store/
git commit -m "feat: sqlite ProfileStore with active-profile tracking"
```

---

### Task 7: FastAPI app — health, profile CRUD, ingest preview, analyze stub

**Files:**
- Create: `src/gaa/api/__init__.py` (empty)
- Create: `src/gaa/api/app.py`
- Test: `tests/api/test_app.py`
- Create: `tests/api/__init__.py` (empty)

The `/analyze` endpoint is a stub here (returns HTTP 501); Plan 2 fills it in. The contract it will satisfy is documented in the route docstring so Plan 2 has the exact shape.

- [ ] **Step 1: Write the failing test**

`tests/api/test_app.py`:
```python
from fastapi.testclient import TestClient
from gaa.api.app import create_app

def _client(tmp_path):
    return TestClient(create_app(db_path=str(tmp_path / "api.sqlite")))

def test_health(tmp_path):
    r = _client(tmp_path).get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"

def test_create_and_list_profile(tmp_path):
    c = _client(tmp_path)
    body = {
        "name": "MyGame", "platform": "roblox", "genre": "survival",
        "mapping": {"date_col": "Date", "metric_cols": {"DAU": "dau"}, "dim_cols": {}},
    }
    r = c.post("/profiles", json=body)
    assert r.status_code == 201 and r.json()["name"] == "MyGame"
    assert "MyGame" in c.get("/profiles").json()["names"]

def test_ingest_preview_returns_canonical_sample(tmp_path):
    c = _client(tmp_path)
    body = {
        "adapter": "roblox",
        "csv_path": "src/gaa/data/sample/roblox_export.csv",
    }
    r = c.post("/ingest/preview", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["row_count"] == 18  # 6 rows x 3 mapped metrics (dau, retention_d7, revenue,...) 
    assert "dau" in data["metrics"]

def test_analyze_stub_not_implemented(tmp_path):
    r = _client(tmp_path).post("/analyze", json={"query": "what happened?"})
    assert r.status_code == 501
```

> Note: the Roblox default mapping maps 4 metrics (dau, retention_d1, retention_d7, revenue) over 6 rows = 24 rows. Adjust the asserted `row_count` to `24` and `metrics` to include all four when implementing — verify against the actual default mapping in Task 5.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gaa.api.app'`.

- [ ] **Step 3: Write minimal implementation**

`src/gaa/api/app.py`:
```python
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from gaa.config import Settings
from gaa.schema.profile import GameProfile, ColumnMapping
from gaa.store.profile_store import ProfileStore
from gaa.adapters.csv_adapter import CSVAdapter
from gaa.adapters.roblox_adapter import RobloxAdapter, DEFAULT_ROBLOX_MAPPING


class IngestPreview(BaseModel):
    adapter: str                      # "csv" | "roblox"
    csv_path: str
    mapping: Optional[ColumnMapping] = None


class AnalyzeRequest(BaseModel):
    query: str
    game: Optional[str] = None


def create_app(db_path: Optional[str] = None) -> FastAPI:
    settings = Settings()
    store = ProfileStore(db_path or settings.db_path)
    app = FastAPI(title="Game Attribution Agent")

    @app.get("/health")
    def health():
        return {"status": "ok", "model": settings.model}

    @app.post("/profiles", status_code=201)
    def create_profile(profile: GameProfile):
        store.save(profile)
        store.set_active(profile.name)
        return {"name": profile.name}

    @app.get("/profiles")
    def list_profiles():
        return {"names": store.list_names()}

    @app.post("/ingest/preview")
    def ingest_preview(req: IngestPreview):
        if req.adapter == "roblox":
            df = RobloxAdapter().load(req.csv_path, req.mapping or DEFAULT_ROBLOX_MAPPING)
        elif req.adapter == "csv":
            if req.mapping is None:
                raise HTTPException(400, "csv adapter requires a mapping")
            df = CSVAdapter().load(req.csv_path, req.mapping)
        else:
            raise HTTPException(400, f"unknown adapter '{req.adapter}'")
        return {
            "row_count": int(len(df)),
            "metrics": sorted(df["metric"].unique().tolist()),
            "head": df.head(5).astype(str).to_dict(orient="records"),
        }

    @app.post("/analyze")
    def analyze(req: AnalyzeRequest):
        # CONTRACT (implemented in Plan 2):
        #   returns {"html": str, "hypothesis": AttributionHypothesis-json,
        #            "markdown_summary": str}
        return JSONResponse(status_code=501, content={"detail": "analyze implemented in Plan 2"})

    return app


app = create_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_app.py -v`
Expected: PASS (adjust `row_count`/`metrics` assertions to match the real Roblox default mapping, then green).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/api/ tests/api/
git commit -m "feat: FastAPI app (health, profile CRUD, ingest preview, analyze stub)"
```

---

### Task 8: Dockerfile + local container run

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Create `.dockerignore`**

```
.venv
.git
__pycache__
*.sqlite
data/cache
tests
```

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
RUN pip install --no-cache-dir -e .
ENV GAA_DB_PATH=/app/gaa.sqlite
EXPOSE 8080
CMD ["uvicorn", "gaa.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 3: Build and run locally, verify health**

Run:
```bash
docker build -t gaa:dev .
docker run -d -p 8080:8080 --name gaa-dev gaa:dev
sleep 3 && curl -s localhost:8080/health
```
Expected: `{"status":"ok","model":"claude-haiku-4-5-20251001"}`

- [ ] **Step 4: Stop container**

Run: `docker rm -f gaa-dev`

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "build: container image serving the FastAPI app"
```

---

### Task 9: Deploy hello-world to AgentBase (manual verification)

**Files:**
- Modify: `README.md` (add deploy notes + declare external model use)

> This task de-risks deployment on Day 1. It involves platform-specific steps from the AgentBase training/manual — capture the exact commands in the README as you go so the team can repeat them.

- [ ] **Step 1: Push the repo to the AgentBase-linked GitHub repo**

Run:
```bash
git remote add origin <agentbase-project-repo-url>
git push -u origin main
```
Expected: push succeeds.

- [ ] **Step 2: Deploy the container per the AgentBase manual**

Follow the AgentBase deploy flow (from training) to build/run this image. Set env vars: `ANTHROPIC_API_KEY`, optionally `GAA_MODEL`, `GAA_MAAS_BASE_URL`, `GAA_MAAS_MODEL`.

- [ ] **Step 3: Verify the deployed endpoint responds**

Run (replace with the AgentBase-exposed URL):
```bash
curl -s <agentbase-endpoint>/health
```
Expected: `{"status":"ok",...}` — this satisfies pass/fail criterion #1 (judges can make ≥1 successful request).

- [ ] **Step 4: Record exact deploy steps + model declaration in README**

Add a "Deployment" section to `README.md` with the exact AgentBase steps used, and a "Models" line declaring external Claude use + MaaS fallback (required by the rulebook).

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: AgentBase deploy steps + external-model declaration"
```

---

## Self-Review (completed during authoring)

**Spec coverage (Plan 1 portion):**
- Canonical schema → Task 2 ✓
- CSV + Roblox adapters → Tasks 4, 5 ✓
- GameProfile + store → Tasks 3, 6 ✓
- API service skeleton + judge-callable health → Tasks 7, 9 ✓
- Docker + AgentBase deploy (Day-1 de-risk) → Tasks 8, 9 ✓
- External-model declaration (README) → Task 9 ✓
- Deferred to Plan 2: orchestrator, 4 modules, Evidence Ledger, synthesizer, dual-confidence, citation validator. Deferred to Plan 3: chat-assisted onboarding (uses the `ingest/preview` + `/profiles` endpoints built here), crawler+cache, Plotly/Jinja2 report renderer, demo/README packaging.

**Placeholder scan:** No TBD/TODO. The one ambiguity (Roblox default mapping → preview `row_count`) is called out with the exact resolution step (verify against Task 5's mapping; 4 metrics × 6 rows = 24).

**Type consistency:** `ColumnMapping(date_col, metric_cols, dim_cols)` and `GameProfile(name, platform, genre, mapping, external_source_config, created_at)` are used identically in Tasks 3, 4, 5, 6, 7. `validate_canonical` / `empty_canonical` / `CANONICAL_DIMS` consistent across Tasks 2, 4. `ProfileStore.save/get/list_names/set_active/get_active` consistent across Tasks 6, 7. `/analyze` stub contract matches the Plan 2 return shape (`html`, `hypothesis`, `markdown_summary`).
