# Flexible Data Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the agent ingest messy, inconsistently-formatted game data — Excel/JSON/JSONL/other-delimited files and tables pasted into chat, in either wide or long layout, with unknown metrics/dimensions preserved instead of dropped — behind a confidence-gated confirm step.

**Architecture:** Three deterministic layers around one LLM step. A **Reader layer** sniffs any supported format into a `RawTable`. An upgraded **Profiler** (the only LLM step) emits a declarative **`IngestionPlan`** (orientation + column mappings *with passthrough* + confidence). A deterministic **`PlanAdapter`** executes the plan into the canonical long frame, which now has an **open schema** that keeps unknown dimensions. Two downstream modules switch from a hardcoded dim list to "dims actually present." Errors become structured, user-facing dicts.

**Tech Stack:** Python 3.11, pandas 2.3, pydantic, FastAPI, pytest. New dependency: `openpyxl` (Excel). Test runner: `.venv/bin/python -m pytest`.

**Reference spec:** `docs/superpowers/specs/2026-06-17-flexible-data-ingestion-design.md`

**Conventions for every task below:**
- Run a single test with `.venv/bin/python -m pytest <path>::<test> -v`.
- After a task's tests pass, run the **full suite** `.venv/bin/python -m pytest -q` before committing, unless the task says otherwise.
- Commit messages use the existing convention (`feat(ingest): …`, `test(ingest): …`, `refactor(ingest): …`).

---

## Task 1: Open canonical schema (preserve extra dims + `dim_columns` helper)

**Files:**
- Modify: `src/gaa/core/schema/canonical.py`
- Test: `tests/schema/test_canonical.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/schema/test_canonical.py`:

```python
def test_validate_canonical_preserves_extra_dim():
    import pandas as pd
    from gaa.core.schema.canonical import validate_canonical
    df = pd.DataFrame({"date": ["2026-05-01"], "metric": ["ccu"], "value": [200],
                       "game_mode": ["ranked"]})
    out = validate_canonical(df)
    assert "game_mode" in out.columns
    assert out.iloc[0]["game_mode"] == "ranked"
    # canonical dims still materialized as None when absent
    assert "region" in out.columns and out.iloc[0]["region"] is None


def test_dim_columns_orders_canonical_then_extra_sorted():
    import pandas as pd
    from gaa.core.schema.canonical import dim_columns
    df = pd.DataFrame(columns=["date", "metric", "value", "game_mode", "region", "ab_group"])
    assert dim_columns(df) == ["region", "ab_group", "game_mode"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/schema/test_canonical.py -v`
Expected: FAIL — `ImportError: cannot import name 'dim_columns'` and the extra-dim test failing because `validate_canonical` returns only `ALL_COLUMNS`.

- [ ] **Step 3: Rewrite `canonical.py`**

Replace the entire contents of `src/gaa/core/schema/canonical.py` with:

```python
import pandas as pd

REQUIRED_COLUMNS = ["date", "metric", "value"]
CANONICAL_DIMS = ["platform", "region", "version", "cohort", "device", "source"]
ALL_COLUMNS = REQUIRED_COLUMNS + CANONICAL_DIMS

_NON_DIM = set(REQUIRED_COLUMNS)


def dim_columns(df: pd.DataFrame) -> list[str]:
    """All dimension columns present: canonical dims first (in canonical order),
    then any extra/custom dims (sorted), excluding date/metric/value."""
    present = [c for c in CANONICAL_DIMS if c in df.columns]
    extra = sorted(c for c in df.columns if c not in _NON_DIM and c not in CANONICAL_DIMS)
    return present + extra


def empty_canonical() -> pd.DataFrame:
    return pd.DataFrame(columns=ALL_COLUMNS)


def validate_canonical(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"canonical frame missing required columns: {missing}")
    out = df.copy()
    # Parse to UTC then drop the tz: some exports carry a 'Z' suffix (tz-aware), but every
    # downstream comparison builds tz-naive Timestamps; a tz-aware column matches zero rows.
    out["date"] = pd.to_datetime(out["date"], errors="raise", utc=True).dt.tz_localize(None)
    out["value"] = out["value"].astype(float)
    out["metric"] = out["metric"].astype(str)
    # Extra (custom) dims are any column that isn't required + isn't a canonical dim.
    extra_dims = [c for c in out.columns if c not in ALL_COLUMNS]
    for dim in CANONICAL_DIMS + extra_dims:
        if dim not in out.columns:
            out[dim] = None
        else:
            # dims are categorical labels → strings (keep null as None so "3.10" != "3.1")
            out[dim] = out[dim].map(lambda x: str(x) if pd.notna(x) else None)
    return out[REQUIRED_COLUMNS + CANONICAL_DIMS + extra_dims]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/schema/test_canonical.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Run the full suite (extra-dim change is additive; existing tests must stay green)**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — same count as before (515) or more.

- [ ] **Step 6: Commit**

```bash
git add src/gaa/core/schema/canonical.py tests/schema/test_canonical.py
git commit -m "feat(ingest): open canonical schema — preserve extra dims + dim_columns()"
```

---

## Task 2: Downstream uses `dim_columns()` (custom dims become drillable)

**Files:**
- Modify: `src/gaa/core/modules/segment.py`
- Modify: `src/gaa/core/modules/exploration.py`
- Modify: `src/gaa/core/analytics/aggregate.py:30-43` (`metric_series`)
- Test: `tests/modules/test_segment.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/modules/test_segment.py` (uses the existing `AnalysisContext` / `EvidenceLedger` imports already at the top of that file; if they are not imported there, add `from gaa.core.modules.base import AnalysisContext` and `from gaa.core.schema.ledger import EvidenceLedger`):

```python
def test_segment_decomposes_a_custom_dimension():
    import pandas as pd
    from gaa.core.modules.segment import SegmentDecomposition
    from gaa.core.modules.base import AnalysisContext
    from gaa.core.schema.ledger import EvidenceLedger
    # custom dim "game_mode" is NOT in CANONICAL_DIMS; it must still be decomposed
    rows = []
    for mode, (v0, v1) in {"ranked": (100, 50), "casual": (100, 100)}.items():
        rows.append({"date": "2026-05-01", "metric": "dau", "value": v0, "game_mode": mode})
        rows.append({"date": "2026-05-10", "metric": "dau", "value": v1, "game_mode": mode})
    df = pd.DataFrame(rows)
    ctx = AnalysisContext(metrics=df, metric="dau", start="2026-05-01", end="2026-05-10",
                          profile=None)
    ledger = EvidenceLedger()
    SegmentDecomposition().run(ctx, ledger)
    claims = " ".join(e.claim for e in ledger.entries)
    assert "game_mode=ranked" in claims
```

NOTE: If `AnalysisContext` requires more fields than `metrics/metric/start/end/profile`, open `src/gaa/core/modules/base.py`, read its constructor, and fill the minimum required fields (e.g. `profile=None`). Match the construction style already used in the other tests in `tests/modules/`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/modules/test_segment.py::test_segment_decomposes_a_custom_dimension -v`
Expected: FAIL — no claim mentions `game_mode` because `segment.py` only iterates the fixed `DIMS`.

- [ ] **Step 3: Edit `segment.py`**

At the top of `src/gaa/core/modules/segment.py`, add the import:

```python
from gaa.core.schema.canonical import dim_columns
```

Change `__init__` and the dim loop. Replace:

```python
    def __init__(self, dims: list | None = None) -> None:
        self._dims = dims or DIMS
```
with:
```python
    def __init__(self, dims: list | None = None) -> None:
        self._dims = dims  # None → derive from the data at run time
```

Inside `run`, immediately after the `df = ctx.metrics[...]` line, add:

```python
        dims = self._dims if self._dims is not None else dim_columns(ctx.metrics)
```
and change the loop header `for dim in self._dims:` to `for dim in dims:`.

(Leave the module-level `DIMS` constant in place — other code/tests may import it.)

- [ ] **Step 4: Edit `exploration.py`**

In `src/gaa/core/modules/exploration.py`, add to the imports:

```python
from gaa.core.schema.canonical import dim_columns
```

Find every `for dim in CANONICAL_DIMS:` (there is at least one in `_p1_surprise_scan` around line 91; grep the file for all occurrences). For each enclosing function that takes `ctx`, compute the data-derived dim list once near the top of that function:

```python
    dims = dim_columns(ctx.metrics)
```
and replace `for dim in CANONICAL_DIMS:` with `for dim in dims:`.

Run: `grep -n "CANONICAL_DIMS" src/gaa/core/modules/exploration.py` and confirm no remaining *iteration* over `CANONICAL_DIMS` (the import line may be removed if now unused).

- [ ] **Step 5: Edit `aggregate.py` `metric_series`**

In `src/gaa/core/analytics/aggregate.py`, add `dim_columns` to the existing canonical import:

```python
from gaa.core.schema.canonical import CANONICAL_DIMS, dim_columns
```
In `metric_series`, change `for dim in CANONICAL_DIMS:` to `for dim in dim_columns(sub):` so a pre-aggregated label on a *custom* dim is also honored.

- [ ] **Step 6: Run the test + full suite**

Run: `.venv/bin/python -m pytest tests/modules/test_segment.py -v`
Expected: PASS.
Run: `.venv/bin/python -m pytest -q`
Expected: PASS (no regressions — canonical dims are a subset of `dim_columns`).

- [ ] **Step 7: Commit**

```bash
git add src/gaa/core/modules/segment.py src/gaa/core/modules/exploration.py src/gaa/core/analytics/aggregate.py tests/modules/test_segment.py
git commit -m "feat(ingest): segment/exploration/aggregate decompose custom dims via dim_columns()"
```

---

## Task 3: `IngestionPlan` + `ReadSpec` schema

**Files:**
- Create: `src/gaa/core/schema/ingest_plan.py`
- Test: `tests/schema/test_ingest_plan.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/schema/test_ingest_plan.py`:

```python
import pytest
from pydantic import ValidationError
from gaa.core.schema.ingest_plan import ReadSpec, IngestionPlan


def test_wide_plan_valid():
    p = IngestionPlan(read_spec=ReadSpec(format="csv"), orientation="wide",
                      date_col="date", metric_cols={"dau": "dau", "ccu": "ccu"})
    assert p.confidence == 0.0
    assert p.metric_cols["ccu"] == "ccu"


def test_long_plan_valid():
    p = IngestionPlan(read_spec=ReadSpec(format="json"), orientation="long",
                      date_col="day", long_metric_col="kpi", long_value_col="val")
    assert p.long_metric_col == "kpi"


def test_wide_plan_requires_metric_cols():
    with pytest.raises(ValidationError):
        IngestionPlan(read_spec=ReadSpec(format="csv"), orientation="wide", date_col="date")


def test_long_plan_requires_metric_and_value_cols():
    with pytest.raises(ValidationError):
        IngestionPlan(read_spec=ReadSpec(format="csv"), orientation="long",
                      date_col="date", long_metric_col="kpi")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/schema/test_ingest_plan.py -v`
Expected: FAIL — `ModuleNotFoundError: gaa.core.schema.ingest_plan`.

- [ ] **Step 3: Create the schema**

Create `src/gaa/core/schema/ingest_plan.py`:

```python
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, model_validator


class ReadSpec(BaseModel):
    """How a RawTable was (and must be re-)read. Recorded at propose time so the
    confirm step re-reads the source identically."""
    format: Literal["csv", "excel", "json", "jsonl", "paste"]
    delimiter: Optional[str] = None
    encoding: Optional[str] = None
    sheet: Optional[str] = None
    header_row: int = 0


class IngestionPlan(BaseModel):
    """Declarative recipe (LLM-authored) for turning a RawTable into the canonical
    long frame. Never code."""
    read_spec: ReadSpec
    orientation: Literal["wide", "long"]
    date_col: str
    # WIDE: each metric is its own column →  source_col -> final metric name
    metric_cols: dict[str, str] = {}
    # LONG: one column holds metric names, another holds values
    long_metric_col: Optional[str] = None
    long_value_col: Optional[str] = None
    dim_cols: dict[str, str] = {}       # source_col -> dim name (canonical OR preserved)
    confidence: float = 0.0             # 0.0–1.0 overall
    notes: list[str] = []               # plain-language decisions/uncertainties

    @model_validator(mode="after")
    def _check_orientation_fields(self) -> "IngestionPlan":
        if self.orientation == "wide" and not self.metric_cols:
            raise ValueError("wide plan requires non-empty metric_cols")
        if self.orientation == "long" and not (self.long_metric_col and self.long_value_col):
            raise ValueError("long plan requires long_metric_col and long_value_col")
        return self
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/schema/test_ingest_plan.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/schema/ingest_plan.py tests/schema/test_ingest_plan.py
git commit -m "feat(ingest): IngestionPlan + ReadSpec declarative schema"
```

---

## Task 4: Reader base — `RawTable` + `Reader` protocol

**Files:**
- Create: `src/gaa/core/ingest/__init__.py` (empty)
- Create: `src/gaa/core/ingest/readers/__init__.py` (empty)
- Create: `src/gaa/core/ingest/readers/base.py`
- Test: `tests/ingest/__init__.py` (empty), `tests/ingest/test_reader_base.py`

- [ ] **Step 1: Write the failing test**

Create `tests/ingest/__init__.py` (empty) and `tests/ingest/test_reader_base.py`:

```python
import pandas as pd
from gaa.core.ingest.readers.base import RawTable
from gaa.core.schema.ingest_plan import ReadSpec


def test_rawtable_holds_df_spec_notes():
    rt = RawTable(df=pd.DataFrame({"a": [1]}), read_spec=ReadSpec(format="csv"))
    assert list(rt.df.columns) == ["a"]
    assert rt.read_spec.format == "csv"
    assert rt.notes == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ingest/test_reader_base.py -v`
Expected: FAIL — `ModuleNotFoundError: gaa.core.ingest`.

- [ ] **Step 3: Create the packages + base**

Create empty `src/gaa/core/ingest/__init__.py` and `src/gaa/core/ingest/readers/__init__.py`.

Create `src/gaa/core/ingest/readers/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

import pandas as pd

from gaa.core.schema.ingest_plan import ReadSpec


@dataclass
class RawTable:
    """A raw, not-yet-canonicalized table plus how to re-read it."""
    df: pd.DataFrame
    read_spec: ReadSpec
    notes: list[str] = field(default_factory=list)


class Reader(Protocol):
    def read(self, data: bytes, spec: Optional[ReadSpec] = None) -> RawTable: ...
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ingest/test_reader_base.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/ingest tests/ingest/__init__.py tests/ingest/test_reader_base.py
git commit -m "feat(ingest): RawTable + Reader protocol"
```

---

## Task 5: CSV/delimited reader (auto-delimiter + encoding fallback)

**Files:**
- Create: `src/gaa/core/ingest/readers/csv_reader.py`
- Test: `tests/ingest/test_csv_reader.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/ingest/test_csv_reader.py`:

```python
from gaa.core.ingest.readers.csv_reader import read_csv_bytes


def test_sniffs_semicolon_delimiter():
    data = b"date;dau;region\n2026-05-01;1000;SEA\n"
    rt = read_csv_bytes(data)
    assert list(rt.df.columns) == ["date", "dau", "region"]
    assert rt.read_spec.delimiter == ";"


def test_latin1_fallback():
    data = "date,city\n2026-05-01,São Paulo\n".encode("latin-1")
    rt = read_csv_bytes(data)
    assert rt.df.iloc[0]["city"] == "São Paulo"


def test_na_string_survives():
    data = b"date,region,dau\n2026-05-01,NA,1000\n"
    rt = read_csv_bytes(data)
    # "NA" (North America) must NOT become NaN
    assert rt.df.iloc[0]["region"] == "NA"


def test_respects_spec_delimiter_on_reread():
    from gaa.core.schema.ingest_plan import ReadSpec
    data = b"date;dau\n2026-05-01;5\n"
    rt = read_csv_bytes(data, ReadSpec(format="csv", delimiter=";"))
    assert list(rt.df.columns) == ["date", "dau"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ingest/test_csv_reader.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Create `src/gaa/core/ingest/readers/csv_reader.py`:

```python
from __future__ import annotations

import csv as _csv
import io
from typing import Optional

import pandas as pd

from gaa.core.ingest.readers.base import RawTable
from gaa.core.schema.ingest_plan import ReadSpec

_ENCODINGS = ["utf-8-sig", "utf-8", "latin-1"]


def _decode(data: bytes, forced: Optional[str]) -> tuple[str, str]:
    if forced:
        return data.decode(forced, errors="replace"), forced
    for enc in _ENCODINGS:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace"), "latin-1"


def _sniff_delim(text: str) -> str:
    sample = "\n".join(text.splitlines()[:5])
    try:
        return _csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except Exception:
        return ","


def read_csv_bytes(data: bytes, spec: Optional[ReadSpec] = None) -> RawTable:
    text, enc = _decode(data, spec.encoding if spec else None)
    delimiter = spec.delimiter if (spec and spec.delimiter) else _sniff_delim(text)
    header_row = spec.header_row if spec else 0
    df = pd.read_csv(io.StringIO(text), sep=delimiter, header=header_row,
                     keep_default_na=False, na_values=[""])
    rs = ReadSpec(format="csv", delimiter=delimiter, encoding=enc, header_row=header_row)
    return RawTable(df=df, read_spec=rs, notes=[])
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ingest/test_csv_reader.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/ingest/readers/csv_reader.py tests/ingest/test_csv_reader.py
git commit -m "feat(ingest): delimited reader — auto-delimiter + encoding fallback + NA-safe"
```

---

## Task 6: Excel reader (multi-sheet + header detection) + `openpyxl` dep

**Files:**
- Modify: `pyproject.toml` (add `openpyxl`) + `uv.lock`
- Create: `src/gaa/core/ingest/readers/excel_reader.py`
- Test: `tests/ingest/test_excel_reader.py`

- [ ] **Step 1: Add the dependency**

Run: `uv add openpyxl`
Expected: `pyproject.toml` gains `openpyxl` under dependencies and `uv.lock` updates. Verify:
`.venv/bin/python -c "import openpyxl; print(openpyxl.__version__)"` prints a version.
If `uv add` cannot reach the network, fall back to `.venv/bin/pip install openpyxl` and add
`"openpyxl>=3.1"` to the `dependencies` list in `pyproject.toml` by hand, then re-run the verify.

- [ ] **Step 2: Write the failing tests**

Create `tests/ingest/test_excel_reader.py` (the fixture is generated in-memory; no binary file needed):

```python
import io
import pandas as pd
from gaa.core.ingest.readers.excel_reader import read_excel_bytes


def _xlsx_with_title_row() -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        # row 0 is a title; the real header is on row 1
        df = pd.DataFrame([["Q2 Metrics Export", None, None],
                           ["date", "dau", "region"],
                           ["2026-05-01", 1000, "SEA"]])
        df.to_excel(xw, index=False, header=False, sheet_name="Data")
        pd.DataFrame({"junk": [None]}).to_excel(xw, index=False, sheet_name="Notes")
    return buf.getvalue()


def test_finds_header_row_and_picks_tabular_sheet():
    rt = read_excel_bytes(_xlsx_with_title_row())
    assert rt.read_spec.sheet == "Data"
    assert list(rt.df.columns) == ["date", "dau", "region"]
    assert rt.df.iloc[0]["region"] == "SEA"
    assert rt.read_spec.header_row == 1


def test_reread_with_spec_is_stable():
    from gaa.core.schema.ingest_plan import ReadSpec
    data = _xlsx_with_title_row()
    rt = read_excel_bytes(data, ReadSpec(format="excel", sheet="Data", header_row=1))
    assert list(rt.df.columns) == ["date", "dau", "region"]
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ingest/test_excel_reader.py -v`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement**

Create `src/gaa/core/ingest/readers/excel_reader.py`:

```python
from __future__ import annotations

import io
from typing import Optional

import pandas as pd

from gaa.core.ingest.readers.base import RawTable
from gaa.core.schema.ingest_plan import ReadSpec


def _pick_sheet(xls: pd.ExcelFile, spec: Optional[ReadSpec]) -> str:
    if spec and spec.sheet:
        return spec.sheet
    best, best_score = xls.sheet_names[0], -1
    for name in xls.sheet_names:
        probe = xls.parse(name, header=None, nrows=50)
        score = int(probe.notna().to_numpy().sum())
        if score > best_score:
            best, best_score = name, score
    return best


def _find_header_row(xls: pd.ExcelFile, sheet: str, spec: Optional[ReadSpec]) -> int:
    if spec is not None:
        return spec.header_row
    probe = xls.parse(sheet, header=None, nrows=20)
    for i in range(len(probe)):
        if int(probe.iloc[i].notna().sum()) >= 2:
            return i
    return 0


def read_excel_bytes(data: bytes, spec: Optional[ReadSpec] = None) -> RawTable:
    xls = pd.ExcelFile(io.BytesIO(data), engine="openpyxl")
    sheet = _pick_sheet(xls, spec)
    header_row = _find_header_row(xls, sheet, spec)
    df = xls.parse(sheet, header=header_row, keep_default_na=False, na_values=[""])
    df.columns = [str(c).strip() for c in df.columns]
    notes = []
    if len(xls.sheet_names) > 1:
        notes.append(f"selected sheet '{sheet}' of {xls.sheet_names}")
    rs = ReadSpec(format="excel", sheet=sheet, header_row=header_row)
    return RawTable(df=df, read_spec=rs, notes=notes)
```

- [ ] **Step 5: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/ingest/test_excel_reader.py -v`
Expected: PASS.
Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/gaa/core/ingest/readers/excel_reader.py tests/ingest/test_excel_reader.py
git commit -m "feat(ingest): Excel reader (multi-sheet pick + header-row detection); add openpyxl"
```

---

## Task 7: JSON / JSONL reader

**Files:**
- Create: `src/gaa/core/ingest/readers/json_reader.py`
- Test: `tests/ingest/test_json_reader.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/ingest/test_json_reader.py`:

```python
from gaa.core.ingest.readers.json_reader import read_json_bytes


def test_json_array_of_records():
    data = b'[{"date":"2026-05-01","dau":1000},{"date":"2026-05-02","dau":1100}]'
    rt = read_json_bytes(data)
    assert list(rt.df.columns) == ["date", "dau"]
    assert len(rt.df) == 2
    assert rt.read_spec.format == "json"


def test_jsonl_records():
    data = b'{"date":"2026-05-01","dau":1000}\n{"date":"2026-05-02","dau":1100}\n'
    rt = read_json_bytes(data)
    assert len(rt.df) == 2
    assert rt.read_spec.format == "jsonl"


def test_json_object_with_nested_array():
    data = b'{"rows":[{"date":"2026-05-01","dau":5}]}'
    rt = read_json_bytes(data)
    assert rt.df.iloc[0]["dau"] == 5
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ingest/test_json_reader.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Create `src/gaa/core/ingest/readers/json_reader.py`:

```python
from __future__ import annotations

import json
from typing import Optional

import pandas as pd

from gaa.core.ingest.readers.base import RawTable
from gaa.core.schema.ingest_plan import ReadSpec


def _looks_jsonl(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    try:
        json.loads(lines[0])
        json.loads(lines[1])
        return True
    except Exception:
        return False


def _records(text: str, fmt: Optional[str]) -> tuple[list, str]:
    if fmt == "jsonl" or (fmt is None and _looks_jsonl(text)):
        return [json.loads(ln) for ln in text.splitlines() if ln.strip()], "jsonl"
    obj = json.loads(text)
    if isinstance(obj, list):
        return obj, "json"
    if isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, list):
                return v, "json"
        return [obj], "json"
    return [obj], "json"


def read_json_bytes(data: bytes, spec: Optional[ReadSpec] = None) -> RawTable:
    text = data.decode("utf-8", errors="replace")
    records, fmt = _records(text, spec.format if spec else None)
    df = pd.json_normalize(records)
    return RawTable(df=df, read_spec=ReadSpec(format=fmt), notes=[])
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ingest/test_json_reader.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/ingest/readers/json_reader.py tests/ingest/test_json_reader.py
git commit -m "feat(ingest): JSON/JSONL reader (array, nested array, newline-delimited)"
```

---

## Task 8: Pasted-table reader (markdown + whitespace/TSV)

**Files:**
- Create: `src/gaa/core/ingest/readers/paste_reader.py`
- Test: `tests/ingest/test_paste_reader.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/ingest/test_paste_reader.py`:

```python
from gaa.core.ingest.readers.paste_reader import read_paste


def test_markdown_table():
    text = (
        "| date       | dau  | region |\n"
        "|------------|------|--------|\n"
        "| 2026-05-01 | 1000 | SEA    |\n"
        "| 2026-05-02 | 1100 | SEA    |\n"
    )
    rt = read_paste(text)
    assert list(rt.df.columns) == ["date", "dau", "region"]
    assert len(rt.df) == 2
    assert rt.df.iloc[0]["region"] == "SEA"
    assert rt.read_spec.format == "paste"


def test_tab_separated_paste():
    text = "date\tdau\n2026-05-01\t1000\n2026-05-02\t1100\n"
    rt = read_paste(text)
    assert list(rt.df.columns) == ["date", "dau"]
    assert len(rt.df) == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ingest/test_paste_reader.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Create `src/gaa/core/ingest/readers/paste_reader.py`:

```python
from __future__ import annotations

import io
import re
from typing import Optional

import pandas as pd

from gaa.core.ingest.readers.base import RawTable
from gaa.core.schema.ingest_plan import ReadSpec

# a markdown separator row: only |, -, :, spaces
_MD_SEP = re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$")


def _read_markdown(lines: list[str]) -> pd.DataFrame:
    rows = []
    for ln in lines:
        if _MD_SEP.match(ln) and "-" in ln:
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        rows.append(cells)
    header, *body = rows
    return pd.DataFrame(body, columns=header)


def read_paste(text: str, spec: Optional[ReadSpec] = None) -> RawTable:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        df = pd.DataFrame()
    elif any("|" in ln for ln in lines[:2]):
        df = _read_markdown(lines)
    else:
        df = pd.read_csv(io.StringIO(text), sep=r"\t|\s{2,}", engine="python",
                         keep_default_na=False, na_values=[""])
    return RawTable(df=df, read_spec=ReadSpec(format="paste"), notes=[])
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ingest/test_paste_reader.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/ingest/readers/paste_reader.py tests/ingest/test_paste_reader.py
git commit -m "feat(ingest): pasted-table reader (markdown + tab/whitespace)"
```

---

## Task 9: Format detection + `read_any` dispatcher + `IngestError`

**Files:**
- Create: `src/gaa/core/ingest/detect.py`
- Test: `tests/ingest/test_detect.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/ingest/test_detect.py`:

```python
import io
import pytest
import pandas as pd
from gaa.core.ingest import detect
from gaa.core.ingest.detect import read_any, IngestError


def _xlsx() -> bytes:
    buf = io.BytesIO()
    pd.DataFrame({"date": ["2026-05-01"], "dau": [5]}).to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def test_routes_csv_by_default():
    rt = read_any(content=b"date,dau\n2026-05-01,1000\n", filename="x.csv")
    assert rt.read_spec.format == "csv"


def test_routes_excel_by_magic_and_extension():
    rt = read_any(content=_xlsx(), filename="report.xlsx")
    assert rt.read_spec.format == "excel"
    # magic-byte detection even without a helpful name
    rt2 = read_any(content=_xlsx(), filename="report.bin")
    assert rt2.read_spec.format == "excel"


def test_routes_json_by_content():
    rt = read_any(content=b'[{"date":"2026-05-01","dau":5}]', filename="d.json")
    assert rt.read_spec.format == "json"


def test_routes_paste_text():
    rt = read_any(text="date\tdau\n2026-05-01\t5\n")
    assert rt.read_spec.format == "paste"


def test_empty_content_raises_ingest_error():
    with pytest.raises(IngestError) as e:
        read_any(content=b"")
    assert e.value.code == "unreadable_file"


def test_reread_by_spec_uses_format():
    from gaa.core.schema.ingest_plan import ReadSpec
    rt = read_any(content=b"date;dau\n2026-05-01;5\n",
                  spec=ReadSpec(format="csv", delimiter=";"))
    assert list(rt.df.columns) == ["date", "dau"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/ingest/test_detect.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Create `src/gaa/core/ingest/detect.py`:

```python
from __future__ import annotations

import os
from typing import Optional

from gaa.core.ingest.readers import csv_reader, excel_reader, json_reader, paste_reader
from gaa.core.ingest.readers.base import RawTable
from gaa.core.schema.ingest_plan import ReadSpec


class IngestError(Exception):
    """A structured, user-facing ingestion failure."""
    def __init__(self, code: str, detail: str = "", hint: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail
        self.hint = hint

    def as_dict(self) -> dict:
        return {"status": "error", "error": self.code,
                "detail": self.detail, "hint": self.hint}


_XLSX_MAGIC = b"PK\x03\x04"
_SUPPORTED = "supported: CSV/TSV, Excel (.xlsx), JSON/JSONL, or a pasted table"


def _detect_format(data: bytes, filename: Optional[str]) -> str:
    ext = os.path.splitext(filename)[1].lower() if filename else ""
    if ext in (".xlsx", ".xlsm", ".xls"):
        return "excel"
    if ext == ".json":
        return "json"
    if ext in (".jsonl", ".ndjson"):
        return "jsonl"
    if data[:4] == _XLSX_MAGIC:
        return "excel"
    head = data[:64].lstrip()
    if head[:1] in (b"{", b"["):
        return "json"
    return "csv"


def _read_by_format(fmt: str, content: Optional[bytes], text: Optional[str],
                    spec: Optional[ReadSpec]) -> RawTable:
    try:
        if fmt == "paste":
            body = text if text is not None else (content or b"").decode("utf-8", "replace")
            return paste_reader.read_paste(body, spec)
        if fmt == "excel":
            return excel_reader.read_excel_bytes(content, spec)
        if fmt in ("json", "jsonl"):
            return json_reader.read_json_bytes(content, spec)
        return csv_reader.read_csv_bytes(content, spec)
    except IngestError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise IngestError("unreadable_file", str(exc), _SUPPORTED) from exc


def read_any(*, content: Optional[bytes] = None, filename: Optional[str] = None,
             text: Optional[str] = None, spec: Optional[ReadSpec] = None) -> RawTable:
    """Single entrypoint. With `spec`, re-read deterministically by its format.
    Otherwise detect from `text` (paste) or `content`+`filename`."""
    if spec is not None:
        return _read_by_format(spec.format, content, text, spec)
    if text is not None:
        return paste_reader.read_paste(text)
    if not content:
        raise IngestError("unreadable_file", "no content provided",
                          "attach a file or paste a table — " + _SUPPORTED)
    return _read_by_format(_detect_format(content, filename), content, text, None)
```

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/ingest/test_detect.py -v`
Expected: PASS.
Run: `.venv/bin/python -m pytest tests/ingest -q`
Expected: PASS (whole reader layer).

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/ingest/detect.py tests/ingest/test_detect.py
git commit -m "feat(ingest): format detection + read_any dispatcher + IngestError"
```

---

## Task 10: Upgrade `Profiler` to emit an `IngestionPlan`

**Files:**
- Modify: `src/gaa/core/onboarding/profiler.py`
- Test: `tests/onboarding/test_profiler.py` (rewrite — the old `ColumnMapping` API is gone)

- [ ] **Step 1: Rewrite the test**

Replace the entire contents of `tests/onboarding/test_profiler.py`:

```python
from gaa.core.onboarding.profiler import Profiler
from gaa.core.llm.client import FakeLLM
from gaa.core.ingest.readers.base import RawTable
from gaa.core.schema.ingest_plan import IngestionPlan, ReadSpec
import pandas as pd


def _raw():
    df = pd.DataFrame({"dt": ["2026-05-01"], "dau_count": [100], "ccu": [20],
                       "country": ["SEA"]})
    return RawTable(df=df, read_spec=ReadSpec(format="csv", delimiter=","))


def test_propose_returns_wide_plan_with_passthrough():
    preset = {"orientation": "wide", "date_col": "dt",
              "metric_cols": {"dau_count": "dau", "ccu": "ccu"},
              "dim_cols": {"country": "region"}, "confidence": 0.9, "notes": []}
    plan = Profiler(FakeLLM(preset)).propose(_raw())
    assert isinstance(plan, IngestionPlan)
    assert plan.read_spec.format == "csv"          # read_spec comes from the RawTable
    assert plan.metric_cols["ccu"] == "ccu"        # passthrough metric kept
    assert plan.confidence == 0.9


def test_summary_mentions_format_and_mappings():
    plan = IngestionPlan(read_spec=ReadSpec(format="excel"), orientation="wide",
                         date_col="dt", metric_cols={"dau_count": "dau"},
                         dim_cols={"country": "region"}, confidence=0.5)
    preview = pd.DataFrame({"date": ["2026-05-01"], "metric": ["dau"], "value": [100.0]})
    msg = Profiler(FakeLLM({})).summary(plan, preview)
    assert "excel" in msg and "dt" in msg and "dau" in msg and "50%" in msg
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/onboarding/test_profiler.py -v`
Expected: FAIL — `propose` still returns a `ColumnMapping` / takes a DataFrame; `summary` doesn't exist.

- [ ] **Step 3: Rewrite `profiler.py`**

Replace the entire contents of `src/gaa/core/onboarding/profiler.py`:

```python
import pandas as pd

from gaa.core.llm.client import LLM
from gaa.core.ingest.readers.base import RawTable
from gaa.core.schema.ingest_plan import IngestionPlan

SYSTEM = (
    "You map a game-metrics table to a canonical long schema.\n"
    "Canonical metric names: dau, mau, revenue, arppu, retention_d1, retention_d7, "
    "retention_d30, sessions, playtime. Canonical dimensions: platform, region, "
    "version, cohort, device, source.\n"
    "Decide orientation: 'wide' if each metric is its own column; 'long' if one column "
    "holds metric names and another holds the values.\n"
    "Map a column to a canonical name ONLY when it clearly fits; otherwise KEEP the "
    "column under a normalized snake_case name — do NOT drop columns you don't recognize.\n"
    "Return ONE JSON object: {orientation, date_col, "
    "metric_cols:{source_col->final_metric_name}, long_metric_col, long_value_col, "
    "dim_cols:{source_col->dim_name}, confidence (0.0-1.0), notes:[strings]}. "
    "For wide tables fill metric_cols and leave long_* null; for long tables fill "
    "long_metric_col + long_value_col and leave metric_cols empty. "
    "confidence reflects how sure you are about orientation, the date column, and the mappings."
)


class Profiler:
    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def propose(self, raw: RawTable) -> IngestionPlan:
        cols = list(raw.df.columns)
        head = raw.df.head(5).astype(str).to_dict(orient="records")
        user = f"COLUMNS: {cols}\nSAMPLE ROWS: {head}"
        fields = self._llm.complete_json(SYSTEM, user)
        fields.pop("read_spec", None)  # read_spec is authoritative from the reader
        return IngestionPlan(read_spec=raw.read_spec, **fields)

    def summary(self, plan: IngestionPlan, preview: pd.DataFrame) -> str:
        if plan.orientation == "wide":
            cols = ", ".join(f"{s} → {n}" for s, n in plan.metric_cols.items())
            shape = f"wide layout; metrics: {cols}"
        else:
            shape = (f"long layout; metric names in `{plan.long_metric_col}`, "
                     f"values in `{plan.long_value_col}`")
        dims = ", ".join(f"{s} → {n}" for s, n in plan.dim_cols.items()) or "(none)"
        note_line = ("\n• notes: " + "; ".join(plan.notes)) if plan.notes else ""
        return (
            f"I read this as a {plan.read_spec.format} file:\n"
            f"• date = `{plan.date_col}`\n"
            f"• {shape}\n"
            f"• dimensions: {dims}\n"
            f"• confidence: {plan.confidence:.0%}{note_line}\n\n"
            f"Preview:\n{preview.head(5).to_string(index=False)}\n\n"
            f"Reply 'confirm' to save, or tell me what to fix."
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/onboarding/test_profiler.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/onboarding/profiler.py tests/onboarding/test_profiler.py
git commit -m "feat(ingest): Profiler emits IngestionPlan (orientation + passthrough + confidence)"
```

---

## Task 11: `PlanAdapter` (deterministic wide/long executor + value coercion)

**Files:**
- Create: `src/gaa/core/adapters/plan_adapter.py`
- Test: `tests/adapters/test_plan_adapter.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/adapters/test_plan_adapter.py`:

```python
import pandas as pd
import pytest
from gaa.core.adapters.plan_adapter import PlanAdapter
from gaa.core.schema.ingest_plan import IngestionPlan, ReadSpec
from gaa.core.ingest.detect import IngestError


def _wide_df():
    return pd.DataFrame({
        "date": ["2026-05-01", "2026-05-01"],
        "platform": ["ios", "android"],
        "game_mode": ["ranked", "casual"],
        "dau": ["1,000", "1500"],     # thousands separator must be coerced
        "ccu": [200, 280],
    })


def test_wide_preserves_passthrough_metric_and_dim():
    plan = IngestionPlan(read_spec=ReadSpec(format="csv"), orientation="wide",
                         date_col="date", metric_cols={"dau": "dau", "ccu": "ccu"},
                         dim_cols={"platform": "platform", "game_mode": "game_mode"})
    out = PlanAdapter().load(_wide_df(), plan)
    assert set(out["metric"].unique()) == {"dau", "ccu"}        # ccu kept, not dropped
    assert "game_mode" in out.columns                            # custom dim kept
    dau_ios = out[(out["metric"] == "dau") & (out["platform"] == "ios")]
    assert dau_ios.iloc[0]["value"] == 1000.0                    # "1,000" → 1000.0


def test_long_orientation():
    df = pd.DataFrame({"day": ["2026-05-01", "2026-05-01"],
                       "kpi": ["dau", "revenue"], "val": [1000, 500],
                       "country": ["SEA", "SEA"]})
    plan = IngestionPlan(read_spec=ReadSpec(format="json"), orientation="long",
                         date_col="day", long_metric_col="kpi", long_value_col="val",
                         dim_cols={"country": "region"})
    out = PlanAdapter().load(df, plan)
    assert set(out["metric"].unique()) == {"dau", "revenue"}
    assert out[out["metric"] == "revenue"].iloc[0]["region"] == "SEA"


def test_currency_and_percent_coercion():
    df = pd.DataFrame({"date": ["2026-05-01"], "revenue": ["$1,234"], "ret": ["45%"]})
    plan = IngestionPlan(read_spec=ReadSpec(format="csv"), orientation="wide",
                         date_col="date", metric_cols={"revenue": "revenue", "ret": "retention_d1"})
    out = PlanAdapter().load(df, plan)
    assert out[out["metric"] == "revenue"].iloc[0]["value"] == 1234.0
    assert out[out["metric"] == "retention_d1"].iloc[0]["value"] == 45.0


def test_missing_column_raises_plan_mismatch():
    plan = IngestionPlan(read_spec=ReadSpec(format="csv"), orientation="wide",
                         date_col="date", metric_cols={"nope": "dau"})
    with pytest.raises(IngestError) as e:
        PlanAdapter().load(pd.DataFrame({"date": ["2026-05-01"], "dau": [1]}), plan)
    assert e.value.code == "plan_mismatch"


def test_all_non_numeric_raises_bad_values():
    plan = IngestionPlan(read_spec=ReadSpec(format="csv"), orientation="wide",
                         date_col="date", metric_cols={"dau": "dau"})
    with pytest.raises(IngestError) as e:
        PlanAdapter().load(pd.DataFrame({"date": ["2026-05-01"], "dau": ["n/a"]}), plan)
    assert e.value.code == "bad_values"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/adapters/test_plan_adapter.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Create `src/gaa/core/adapters/plan_adapter.py`:

```python
from __future__ import annotations

import re

import pandas as pd

from gaa.core.ingest.detect import IngestError
from gaa.core.schema.canonical import validate_canonical
from gaa.core.schema.ingest_plan import IngestionPlan

# strip thousands separators, currency symbols, percent signs, whitespace before float cast
_NUM_JUNK = re.compile(r"[,$€£%\s]")


def _to_float(s: pd.Series) -> pd.Series:
    cleaned = s.astype(str).str.replace(_NUM_JUNK, "", regex=True).replace("", None)
    return pd.to_numeric(cleaned, errors="coerce")


class PlanAdapter:
    """Execute an IngestionPlan against a raw DataFrame → canonical long frame."""

    def load(self, df: pd.DataFrame, plan: IngestionPlan) -> pd.DataFrame:
        try:
            long = self._wide(df, plan) if plan.orientation == "wide" else self._long(df, plan)
        except KeyError as exc:
            raise IngestError("plan_mismatch", f"column {exc} not found in the file",
                              "the file's columns don't match the plan — re-propose") from exc
        long["value"] = _to_float(long["value"])
        if bool(long["value"].isna().all()):
            raise IngestError("bad_values", "no numeric values after coercion",
                              "check that the value column(s) hold numbers")
        long = long.dropna(subset=["value"])
        return validate_canonical(long)

    def _wide(self, df: pd.DataFrame, plan: IngestionPlan) -> pd.DataFrame:
        id_vars = [plan.date_col] + list(plan.dim_cols.keys())
        value_vars = list(plan.metric_cols.keys())
        missing = [c for c in id_vars + value_vars if c not in df.columns]
        if missing:
            raise KeyError(missing[0])
        long = df.melt(id_vars=id_vars, value_vars=value_vars,
                       var_name="_src_metric", value_name="value")
        long["metric"] = long["_src_metric"].map(plan.metric_cols)
        long = long.drop(columns=["_src_metric"]).rename(
            columns={plan.date_col: "date", **plan.dim_cols})
        return long

    def _long(self, df: pd.DataFrame, plan: IngestionPlan) -> pd.DataFrame:
        keep = [plan.date_col, plan.long_metric_col, plan.long_value_col] + list(plan.dim_cols.keys())
        missing = [c for c in keep if c not in df.columns]
        if missing:
            raise KeyError(missing[0])
        return df[keep].rename(columns={
            plan.date_col: "date", plan.long_metric_col: "metric",
            plan.long_value_col: "value", **plan.dim_cols})
```

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/adapters/test_plan_adapter.py -v`
Expected: PASS.
Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/adapters/plan_adapter.py tests/adapters/test_plan_adapter.py
git commit -m "feat(ingest): PlanAdapter — wide/long executor, passthrough, value coercion, structured errors"
```

---

## Task 12: `GameProfile` stores the plan

**Files:**
- Modify: `src/gaa/core/schema/profile.py`
- Test: `tests/schema/test_profile.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/schema/test_profile.py`:

```python
def test_profile_round_trips_with_plan():
    from gaa.core.schema.profile import GameProfile
    from gaa.core.schema.ingest_plan import IngestionPlan, ReadSpec
    plan = IngestionPlan(read_spec=ReadSpec(format="excel", sheet="Data"),
                         orientation="wide", date_col="date",
                         metric_cols={"dau": "dau"}, confidence=0.9)
    p = GameProfile(name="g", platform="roblox", genre="rpg", plan=plan)
    again = GameProfile.model_validate_json(p.model_dump_json())
    assert again.plan.read_spec.sheet == "Data"
    assert again.plan.metric_cols["dau"] == "dau"
    assert again.mapping is None   # legacy field now optional
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/schema/test_profile.py::test_profile_round_trips_with_plan -v`
Expected: FAIL — `GameProfile` has required `mapping`, no `plan` field.

- [ ] **Step 3: Edit `profile.py`**

In `src/gaa/core/schema/profile.py`, add the import near the top:

```python
from gaa.core.schema.ingest_plan import IngestionPlan
```

In `GameProfile`, make `mapping` optional and add `plan`. Replace the line `mapping: ColumnMapping` with:

```python
    plan: Optional[IngestionPlan] = None
    mapping: Optional[ColumnMapping] = None  # legacy (wide-only); superseded by plan
```

(`Optional` is already imported in this file.)

- [ ] **Step 4: Run to verify pass + full suite**

Run: `.venv/bin/python -m pytest tests/schema/test_profile.py -v`
Expected: PASS.
Run: `.venv/bin/python -m pytest -q`
Expected: PASS — making `mapping` optional doesn't break existing construction.

- [ ] **Step 5: Commit**

```bash
git add src/gaa/core/schema/profile.py tests/schema/test_profile.py
git commit -m "feat(ingest): GameProfile stores the full IngestionPlan (mapping now legacy/optional)"
```

---

## Task 13: Rewire onboarding handlers (`onboard_propose` / `onboard_confirm`)

**Files:**
- Modify: `src/gaa/cli/commands/onboarding.py`
- Test: `tests/server/test_onboard_upload.py` (rewrite to the new API)
- Check/adjust: `tests/cli/test_onboarding.py` (if it asserts the old `mapping` shape)

- [ ] **Step 1: Rewrite the test**

Replace the entire contents of `tests/server/test_onboard_upload.py`:

```python
import base64
import json
import io
from types import SimpleNamespace

import pandas as pd

from gaa.cli.wiring import build_context
from gaa.core.llm.client import FakeLLM
from gaa.cli.commands.onboarding import cmd_onboard_propose, cmd_onboard_confirm

# FakeLLM returns this plan body for the profiler (read_spec is added from the RawTable)
_PLAN_BODY = {"orientation": "wide", "date_col": "day",
              "metric_cols": {"dau": "dau", "ccu": "ccu"},
              "dim_cols": {"region": "region"}, "confidence": 0.95, "notes": []}
_CSV = "day,region,dau,ccu\n2026-05-01,SEA,1000,200\n2026-05-03,SEA,400,80\n"
_B64 = base64.b64encode(_CSV.encode()).decode()


def _ctx(tmp_path, monkeypatch, preset):
    monkeypatch.setenv("GAA_DB_PATH", str(tmp_path / "gaa.sqlite"))
    monkeypatch.setenv("GAA_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("GAA_CONFIG_PATH", str(tmp_path / "gaa-config.toml"))
    return build_context(llm=FakeLLM(preset), today="2026-06-13")


def test_propose_returns_plan_and_auto_ok(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, _PLAN_BODY)
    args = SimpleNamespace(content_b64=_B64, filename="MyGame.csv")
    r = cmd_onboard_propose(ctx, args)
    assert r["status"] == "success"
    assert r["plan"]["orientation"] == "wide"
    assert r["plan"]["metric_cols"]["ccu"] == "ccu"   # passthrough survives
    assert r["auto_ok"] is True                        # confidence 0.95 ≥ 0.8, no notes
    assert "ccu" in str(r["preview"])


def test_confirm_ingests_via_plan(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, {})
    plan = dict(_PLAN_BODY, read_spec={"format": "csv", "delimiter": ",",
                                       "encoding": "utf-8", "header_row": 0})
    args = SimpleNamespace(content_b64=_B64, plan=json.dumps(plan),
                           name="G", platform="roblox", genre="survival")
    r = cmd_onboard_confirm(ctx, args)
    assert r["status"] == "success"
    assert r["row_count"] == 4                          # 2 dates × 2 metrics
    assert set(r["metrics"]) == {"ccu", "dau"}


def test_propose_from_pasted_text(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, _PLAN_BODY)
    text = "day\tregion\tdau\tccu\n2026-05-01\tSEA\t1000\t200\n"
    args = SimpleNamespace(text=text)
    r = cmd_onboard_propose(ctx, args)
    assert r["status"] == "success" and r["plan"]["read_spec"]["format"] == "paste"


def test_propose_unreadable_returns_structured_error(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch, _PLAN_BODY)
    r = cmd_onboard_propose(ctx, SimpleNamespace())
    assert r["status"] == "error" and r["error"] == "unreadable_file"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/server/test_onboard_upload.py -v`
Expected: FAIL — handlers still use the old `_read_csv` / `mapping` API.

- [ ] **Step 3: Rewrite `onboarding.py`**

Replace the entire contents of `src/gaa/cli/commands/onboarding.py`:

```python
from __future__ import annotations

import base64
import json
from typing import Optional

from gaa.core.ingest import detect
from gaa.core.ingest.detect import IngestError
from gaa.core.ingest.readers.base import RawTable
from gaa.core.adapters.plan_adapter import PlanAdapter
from gaa.core.schema.ingest_plan import IngestionPlan, ReadSpec
from gaa.core.schema.profile import GameProfile

AUTO_CONFIDENCE = 0.8


def _content_b64(args) -> Optional[str]:
    # content_b64 is the canonical field; csv_b64 is the legacy alias.
    return getattr(args, "content_b64", None) or getattr(args, "csv_b64", None)


def _read(args, spec: Optional[ReadSpec] = None) -> RawTable:
    """Read from pasted text, base64 content (any format), or a file path."""
    text = getattr(args, "text", None)
    if text:
        return detect.read_any(text=text, spec=spec)
    b64 = _content_b64(args)
    fname = getattr(args, "filename", None)
    if b64:
        return detect.read_any(content=base64.b64decode(b64), filename=fname, spec=spec)
    path = getattr(args, "csv", None)
    if path:
        with open(path, "rb") as f:
            return detect.read_any(content=f.read(), filename=fname or path, spec=spec)
    raise IngestError("unreadable_file", "no input provided",
                      "attach a file or paste a table")


def _plan_arg(args) -> IngestionPlan:
    raw = args.plan
    data = json.loads(raw) if isinstance(raw, str) else raw
    return IngestionPlan(**data)


def cmd_onboard_propose(ctx, args) -> dict:
    try:
        raw = _read(args)
    except IngestError as e:
        return e.as_dict()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": "unreadable_file", "detail": str(exc),
                "hint": "supported: CSV/TSV, Excel, JSON/JSONL, or a pasted table"}

    plan = None
    for _ in range(2):  # retry once on an invalid plan from the model
        try:
            plan = ctx.profiler.propose(raw)
            break
        except Exception:
            plan = None
    if plan is None:
        return {"status": "error", "error": "cannot_interpret",
                "detail": f"columns: {list(raw.df.columns)}",
                "hint": "tell me which column is the date and which are the metrics"}

    try:
        preview_df = PlanAdapter().load(raw.df, plan).head(8)
    except IngestError:
        preview_df = raw.df.head(5)

    return {
        "status": "success",
        "plan": plan.model_dump(),
        "summary": ctx.profiler.summary(plan, preview_df),
        "preview": preview_df.astype(str).to_dict(orient="records"),
        "confidence": plan.confidence,
        "auto_ok": plan.confidence >= AUTO_CONFIDENCE and not plan.notes,
    }


def cmd_onboard_confirm(ctx, args) -> dict:
    try:
        plan = _plan_arg(args)
        raw = _read(args, spec=plan.read_spec)
        df = PlanAdapter().load(raw.df, plan)
        ctx.metrics.save(args.name, df)
        profile = GameProfile(name=args.name, platform=args.platform,
                              genre=args.genre, plan=plan)
        from gaa.core.crawl.roblox_title import universe_id_from, lookup_universe_title
        if getattr(profile, "title", None) is None and profile.platform == "roblox":
            uid = universe_id_from(profile.name)
            if uid:
                profile.title = lookup_universe_title(uid)
        ctx.profiles.save(profile)
        ctx.profiles.set_active(args.name)
    except IngestError as e:
        return e.as_dict()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}
    return {
        "status": "success",
        "name": args.name,
        "row_count": int(len(df)),
        "metrics": sorted(df["metric"].unique().tolist()),
    }


def cmd_profile_list(ctx, args) -> dict:
    active = ctx.profiles.get_active()
    return {
        "status": "success",
        "profiles": ctx.profiles.list_names(),
        "active": active.name if active else None,
    }


def cmd_profile_use(ctx, args) -> dict:
    if args.name not in ctx.profiles.list_names():
        return {"status": "error", "error": f"unknown profile: {args.name!r}"}
    ctx.profiles.set_active(args.name)
    return {"status": "success", "active": args.name}
```

- [ ] **Step 4: Run the rewritten test**

Run: `.venv/bin/python -m pytest tests/server/test_onboard_upload.py -v`
Expected: PASS.

- [ ] **Step 5: Fix any other onboarding tests broken by the API change**

Run: `.venv/bin/python -m pytest tests/cli/test_onboarding.py -v`
If it fails because it builds `SimpleNamespace(csv=…, mapping=…)` and asserts `"mapping" in r`:
- Update its propose call to assert the new keys (`r["plan"]`, `r["auto_ok"]`).
- Update its confirm call to pass `plan=json.dumps({... , "read_spec": {"format":"csv"}})` instead of `mapping=…`.
Mirror the patterns from `tests/server/test_onboard_upload.py` above. (If the file does not exercise propose/confirm directly, no change needed.)

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS except possibly `tests/server/test_upload.py` (fixed in Task 14). If only that file fails, proceed to Task 14; otherwise fix the failing onboarding-related test here.

- [ ] **Step 7: Commit**

```bash
git add src/gaa/cli/commands/onboarding.py tests/server/test_onboard_upload.py tests/cli/test_onboarding.py
git commit -m "feat(ingest): onboarding handlers use read_any + IngestionPlan + confidence gate"
```

---

## Task 14: Front door `/upload` + MCP tool specs accept any format

**Files:**
- Modify: `src/gaa/server/app.py` (`_onboard_from_csv` → plan-based; widen `/upload`)
- Modify: `src/gaa/mcp/tools.py` (`onboard_propose` / `onboard_confirm` specs)
- Test: `tests/server/test_upload.py` (adjust to the new flow)

- [ ] **Step 1: Inspect and update the upload test**

Open `tests/server/test_upload.py`. It posts a file to `/upload` and asserts success via the old `_onboard_from_csv` (which read `proposed["mapping"]`). Update its FakeLLM preset (or the ctx wiring) to return a **plan body** instead of a mapping, matching `_PLAN_BODY` from Task 13, and keep the upload assertion as `result["status"] == "success"`. If the test builds the ctx with a `FakeLLM`, change the preset to:

```python
{"orientation": "wide", "date_col": "day", "metric_cols": {"dau": "dau"},
 "dim_cols": {"region": "region"}, "confidence": 0.95, "notes": []}
```
and ensure the uploaded CSV has matching columns (`day,region,dau`).

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/server/test_upload.py -v`
Expected: FAIL — `_onboard_from_csv` references `proposed["mapping"]` which no longer exists.

- [ ] **Step 3: Rewrite `_onboard_from_csv` and widen `/upload` in `app.py`**

Replace `_onboard_from_csv` (lines ~67-80) with:

```python
def _onboard_from_upload(ctx, content_b64: str, *, filename: str,
                         name: str, platform: str, genre: str) -> dict:
    """One-shot onboard for the front door: propose a plan, then confirm it.
    Any supported format (CSV/Excel/JSON/JSONL); detection is by filename + content."""
    proposed = actions.dispatch(
        ctx, "onboard_propose", {"content_b64": content_b64, "filename": filename},
        is_admin=False)
    if proposed.get("status") != "success":
        return proposed
    import json as _json
    return actions.dispatch(
        ctx, "onboard_confirm",
        {"content_b64": content_b64, "plan": _json.dumps(proposed["plan"]),
         "name": name, "platform": platform, "genre": genre},
        is_admin=False)
```

In the `upload` route, replace the temp-file + `_onboard_from_csv` block. The new body reads the
bytes, base64-encodes them, and calls the one-shot helper (no temp file, any extension):

```python
    @app.post("/upload")
    async def upload(request: Request):
        require_token(request)
        form = await request.form()
        upload_file = form.get("file")
        if upload_file is None:
            raise HTTPException(status_code=422, detail="file field required")
        data = await upload_file.read()
        original_name = getattr(upload_file, "filename", None) or "uploaded_game"
        game_name = os.path.splitext(original_name)[0].replace(" ", "_") or "uploaded_game"
        platform = form.get("platform", "generic")
        genre = form.get("genre", "casual")
        import base64 as _b64
        content_b64 = _b64.b64encode(data).decode()
        result = _onboard_from_upload(get_ctx(), content_b64, filename=original_name,
                                      name=game_name, platform=platform, genre=genre)
        if isinstance(result, dict) and result.get("status") == "success":
            try:
                persist.snapshot(get_ctx())
            except Exception:
                _log.exception("vStorage snapshot after /upload failed")
        return JSONResponse(result)
```

Remove the now-unused `import tempfile` only if nothing else uses it (grep first: `grep -n tempfile src/gaa/server/app.py`).

- [ ] **Step 4: Update the MCP tool specs in `tools.py`**

In `src/gaa/mcp/tools.py` `_SPECS`, replace the `onboard_propose` and `onboard_confirm` entries:

```python
    "onboard_propose": ("Propose an ingestion plan from a data file or pasted table (onboarding step 1). "
                        "Accepts pasted `text`, base64 `content_b64` (+ `filename` for type hints), or a `csv` path. "
                        "Supports CSV/TSV, Excel (.xlsx), JSON/JSONL. Returns {plan, summary, preview, confidence, auto_ok}.",
                        {"type": "object", "properties": {
                            "text": _STR, "content_b64": _STR, "filename": _STR, "csv": _STR}}),
    "onboard_confirm": ("Confirm an ingestion plan and ingest the data (onboarding step 2). "
                        "Pass the (possibly edited) `plan` JSON plus `name`, `platform`, `genre`, "
                        "and the same source (`text` / `content_b64` / `csv`).",
                        {"type": "object", "properties": {
                            "plan": {"type": "object"}, "name": _STR, "platform": _STR,
                            "genre": _STR, "text": _STR, "content_b64": _STR, "filename": _STR,
                            "csv": _STR}, "required": ["plan", "name"]}),
```

NOTE: the dispatch layer JSON-loads `plan` only if it's a string; passing an object here is fine because `_plan_arg` handles both. Keep `_DEFAULTS["onboard_propose"]`/`["onboard_confirm"]` in `actions.py` — but remove the now-meaningless `"adapter": "generic"` default if present (the new handlers ignore `adapter`). Leaving it is harmless; removing is tidier.

- [ ] **Step 5: Run the upload test + full suite**

Run: `.venv/bin/python -m pytest tests/server/test_upload.py -v`
Expected: PASS.
Run: `.venv/bin/python -m pytest -q`
Expected: PASS (full suite green).

- [ ] **Step 6: Commit**

```bash
git add src/gaa/server/app.py src/gaa/mcp/tools.py tests/server/test_upload.py
git commit -m "feat(ingest): /upload + MCP onboard tools accept Excel/JSON/JSONL/delimited/pasted"
```

---

## Task 15: Update the agent onboarding playbook (formats + confidence gate)

**Files:**
- Modify: `workspace/skills/gaa/references/onboarding.md`
- Check: `openclaw/SOUL.md` and `src/gaa/data/seed/SOUL.md` (only if they state "CSV only")

- [ ] **Step 1: Rewrite `onboarding.md`**

Replace the contents of `workspace/skills/gaa/references/onboarding.md` with:

```markdown
# Onboarding & profiles

Connect a game's data. The agent accepts **CSV/TSV, Excel (.xlsx), JSON/JSONL, or a table
pasted straight into chat**, in either wide (one column per metric) or long layout. Unknown
metrics/dimensions are **kept** (not dropped). Two steps, confidence-gated.

## Step 1 — propose a plan

    onboard_propose(content_b64=<base64 file>, filename="data.xlsx")   # a file
    onboard_propose(text="| date | dau | ... |")                       # a pasted table
    onboard_propose(csv="<path>")                                      # a local path

Returns `{plan, summary, preview, confidence, auto_ok}`.

## Step 2 — confidence gate

- If `auto_ok` is **true** (high confidence, no caveats): call `onboard_confirm` right away,
  then tell the user what you read — format, layout, which columns mapped to canonical names,
  which were kept as custom metrics/dims, and the row count.
- If `auto_ok` is **false** (or `plan.notes` flags anything): show the user `summary` + `preview`
  and ask them to confirm or correct the mapping before you call `onboard_confirm`.

## Step 3 — confirm (ingest)

    onboard_confirm(plan=<the plan JSON, possibly edited>, name="<game>",
                    platform=<roblox|steam|...>, genre="<genre>",
                    content_b64=<same file> | text=<same paste> | csv=<same path>)

On error the tool returns `{status:"error", error:<code>, detail, hint}` — relay the `hint`
to the user (e.g. `unreadable_file`, `no_table_found`, `cannot_interpret`, `plan_mismatch`,
`bad_values`).

## Profiles

    profile_list            # {profiles[], active}
    profile_use <name>      # switch the active game
```

- [ ] **Step 2: Check the SOUL files**

Run: `grep -ni "csv" openclaw/SOUL.md src/gaa/data/seed/SOUL.md`
If either says the agent only accepts CSV (or "must be a CSV"), update that sentence to:
"accepts CSV/TSV, Excel, JSON/JSONL, or a pasted table; unknown columns are preserved." If there
is no such statement, make no change.

- [ ] **Step 3: Commit**

```bash
git add workspace/skills/gaa/references/onboarding.md openclaw/SOUL.md src/gaa/data/seed/SOUL.md
git commit -m "docs(ingest): onboarding playbook — multi-format intake + confidence gate"
```

(If the SOUL files were not changed, only add `onboarding.md`.)

---

## Task 16: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — at least 515 + the new tests; zero failures.

- [ ] **Step 2: Sanity-check the three pain points end-to-end (manual smoke)**

Run this one-off script with the venv python to prove format + passthrough + shape together:

```bash
.venv/bin/python - <<'PY'
import base64, io, json, pandas as pd
from gaa.core.ingest import detect
from gaa.core.adapters.plan_adapter import PlanAdapter
from gaa.core.schema.ingest_plan import IngestionPlan, ReadSpec

# Excel, wide, with a custom metric (ccu) and custom dim (game_mode)
buf = io.BytesIO()
pd.DataFrame({"date": ["2026-05-01","2026-05-01"], "game_mode": ["ranked","casual"],
              "dau": ["1,000","1500"], "ccu": [200,280]}).to_excel(buf, index=False, engine="openpyxl")
rt = detect.read_any(content=buf.getvalue(), filename="m.xlsx")
plan = IngestionPlan(read_spec=rt.read_spec, orientation="wide", date_col="date",
                     metric_cols={"dau":"dau","ccu":"ccu"}, dim_cols={"game_mode":"game_mode"})
out = PlanAdapter().load(rt.df, plan)
assert set(out["metric"].unique()) == {"dau","ccu"}, out["metric"].unique()
assert "game_mode" in out.columns
assert out[(out.metric=="dau")&(out.game_mode=="ranked")].iloc[0]["value"] == 1000.0
print("OK — Excel + passthrough metric/dim + value coercion all work")
PY
```
Expected: prints `OK — …`.

- [ ] **Step 3: Confirm branch state**

Run: `git status` and `git log --oneline -16`
Expected: clean tree; the task commits present in order.

- [ ] **Step 4 (optional): hand off to finishing-a-development-branch**

Once green, use the `superpowers:finishing-a-development-branch` skill to decide merge/PR.
This work is already on `feat/gaa-on-openclaw`; redeploy to `gaa-custom-agent` is a separate,
explicit step (see the GAA-on-OpenClaw memory) and is NOT part of this plan.

---

## Self-review notes (for the implementer)

- **Spec coverage:** formats (Tasks 5-9), shape wide/long (Task 11), passthrough/open-schema
  (Tasks 1, 10, 11), confidence gate (Tasks 10, 13, 15), structured errors (Tasks 9, 11, 13),
  downstream custom dims (Task 2), minimal value coercion (Task 11). All spec sections map to a task.
- **Out of scope (do not build):** Google Sheets/URL fetch, multi-file ingest, dedup/granularity
  reconciliation, re-expressing RobloxAdapter as a plan. `CSVAdapter`/`RobloxAdapter` classes are
  intentionally left in place (still unit-tested) but off the onboarding path.
- **Type consistency:** `read_any(content=, filename=, text=, spec=)`, `RawTable(df, read_spec, notes)`,
  `IngestionPlan(read_spec, orientation, date_col, metric_cols, long_metric_col, long_value_col,
  dim_cols, confidence, notes)`, `PlanAdapter().load(df, plan)`, `Profiler.propose(raw)` /
  `Profiler.summary(plan, preview)`, `IngestError(code, detail, hint)` + `.as_dict()`,
  `dim_columns(df)` — used identically across tasks.
```
