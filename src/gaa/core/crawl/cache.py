import hashlib
import os


class DiskCache:
    def __init__(self, cache_dir: str) -> None:
        self._dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def _path(self, key: str) -> str:
        h = hashlib.sha256(key.encode()).hexdigest()[:32]
        return os.path.join(self._dir, f"{h}.txt")

    def get(self, key: str):
        p = self._path(key)
        return open(p, encoding="utf-8").read() if os.path.exists(p) else None

    def put(self, key: str, value: str) -> None:
        with open(self._path(key), "w", encoding="utf-8") as fh:
            fh.write(value)
