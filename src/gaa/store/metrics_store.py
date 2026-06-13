import os
import re
import pandas as pd
from gaa.schema.canonical import validate_canonical


class MetricsStore:
    def __init__(self, root: str) -> None:
        self._root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, game: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", game)
        return os.path.join(self._root, f"{safe}.parquet")

    def save(self, game: str, df: pd.DataFrame) -> None:
        validate_canonical(df).to_parquet(self._path(game), index=False)

    def load(self, game: str) -> pd.DataFrame:
        path = self._path(game)
        if not os.path.exists(path):
            raise FileNotFoundError(f"no metrics for game '{game}'")
        return validate_canonical(pd.read_parquet(path))
