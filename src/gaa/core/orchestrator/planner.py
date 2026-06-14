import re

# Order matters: specific D1/D7 aliases are checked before the bare word
# "retention" (which falls through to D7) so "day 1 retention" maps to D1.
_METRICS = {
    "revenue": ["revenue", "rev", "earnings", "robux"],
    "dau": ["dau", "active users", "active player", "players"],
    "retention_d1": ["d1 retention", "day 1 retention", "day-1 retention", "1-day retention"],
    "retention_d7": ["d7 retention", "day 7 retention", "day-7 retention", "retention", "retain"],
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
