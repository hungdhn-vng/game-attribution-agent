"""Frozen, md5-verified registry of promoted ad-hoc tools (Tier 2.5).

Layout: <root>/<name>/{tool.py (frozen copy), tool.toml (name, description, md5,
provenance)}. Promotion buys reuse, not trust — tool evidence stays Moderate
(enforced in gaa.lab.add_evidence). `verify` gates execution: a drifted/tampered
tool.py refuses to run rather than silently producing different numbers.
"""
from __future__ import annotations

import hashlib
import shutil
import tarfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import tomli_w


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


class ToolRegistry:
    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _dir(self, name: str) -> Path:
        return self._root / name

    def promote(self, name: str, description: str, script_path: str,
                source_run: str = "", source_script: str = "") -> dict:
        src = Path(script_path)
        if not src.exists():
            raise ValueError(f"script not found: {script_path}")
        d = self._dir(name)
        d.mkdir(parents=True, exist_ok=True)
        tool_py = d / "tool.py"
        shutil.copyfile(src, tool_py)
        meta = {
            "name": name,
            "description": description,
            "md5": _md5(tool_py),
            "provenance": {
                "source_run": source_run,
                "source_script": source_script,
                "promoted_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        with (d / "tool.toml").open("wb") as f:
            tomli_w.dump(meta, f)
        return meta

    def meta(self, name: str) -> dict:
        p = self._dir(name) / "tool.toml"
        if not p.exists():
            raise ValueError(f"unknown tool: {name!r}")
        with p.open("rb") as f:
            return tomllib.load(f)

    def path(self, name: str) -> Path:
        return self._dir(name) / "tool.py"

    def verify(self, name: str) -> bool:
        tp = self.path(name)
        return tp.exists() and _md5(tp) == self.meta(name).get("md5")

    def list(self) -> list[dict]:
        out = []
        for child in sorted(self._root.iterdir()):
            if (child / "tool.toml").exists():
                m = self.meta(child.name)
                out.append({
                    "name": m["name"],
                    "description": m.get("description", ""),
                    "promoted_at": m.get("provenance", {}).get("promoted_at", ""),
                    "md5_ok": self.verify(child.name),
                })
        return out

    def show(self, name: str) -> dict:
        m = self.meta(name)
        return {**m, "md5_ok": self.verify(name), "source": self.path(name).read_text()}

    def remove(self, name: str) -> None:
        d = self._dir(name)
        if not d.exists():
            raise ValueError(f"unknown tool: {name!r}")
        shutil.rmtree(d)

    def sync_docs(self, out_path: str) -> str:
        lines = ["# Promoted tools", ""]
        items = self.list()
        for t in items:
            name = " ".join(str(t["name"]).split())
            desc = " ".join(str(t["description"]).split())
            warn = "" if t["md5_ok"] else "  ⚠️ md5 mismatch — re-promote"
            lines.append(f"- **{name}** — {desc}{warn}")
        if not items:
            lines.append("_(none promoted yet)_")
        text = "\n".join(lines) + "\n"
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        return text

    def export(self, tarball: str) -> None:
        with tarfile.open(tarball, "w:gz") as tar:
            tar.add(self._root, arcname=".")

    def import_(self, tarball: str) -> None:
        with tarfile.open(tarball, "r:gz") as tar:
            tar.extractall(self._root, filter="data")
