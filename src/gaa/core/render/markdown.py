from gaa.core.schema.hypothesis import AttributionHypothesis


def to_markdown(h: AttributionHypothesis) -> str:
    lines = [f"**{h.main_story}** — *{h.confidence.likelihood} · "
             f"{h.confidence.evidence_quality} evidence*", ""]
    if h.causes.internal:
        lines.append("**🔵 Internal**")
        for c in h.causes.internal:
            cites = " ".join(f"`{i}`" for i in c.evidence_ids)
            lines.append(f"- {c.claim} — *{c.likelihood} · {c.evidence_quality}* {cites}")
    if h.causes.market:
        lines.append("**🟠 Market**")
        for c in h.causes.market:
            cites = " ".join(f"`{i}`" for i in c.evidence_ids)
            lines.append(f"- {c.claim} — *{c.likelihood} · {c.evidence_quality}* {cites}")
    if h.scenarios:
        lines.append("\n**Next scenarios:**")
        for s in h.scenarios:
            lines.append(f"- {s.description} — *{s.likelihood} · {s.evidence_quality}*")
    if h.assumptions_and_gaps:
        lines.append("\n**Assumptions/gaps:** " + "; ".join(h.assumptions_and_gaps))
    return "\n".join(lines)
