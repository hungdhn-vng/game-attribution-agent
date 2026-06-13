import re

_METRICS = {
    "revenue": ["revenue", "rev", "earnings", "robux"],
    "dau": ["dau", "active users", "active player", "players"],
    "retention_d7": ["d7 retention", "retention", "retain"],
    "retention_d1": ["d1 retention"],
}


def parse_query(query: str) -> dict:
    q = query.lower()
    metric = None
    for canon, aliases in _METRICS.items():
        if any(a in q for a in aliases):
            metric = canon
            break
    direction = "down" if re.search(r"drop|fell|down|decline|crash|lost", q) else (
        "up" if re.search(r"spike|grew|rose|up|surge|gain", q) else None)
    return {"metric": metric, "direction": direction}
