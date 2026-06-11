from gaa.schema.ledger import LedgerEntry, EvidenceLedger


def test_add_assigns_sequential_ids():
    led = EvidenceLedger()
    i1 = led.add(module="anomaly", claim="dau -25%", value="-0.25",
                 source="internal:dau", source_type="internal", strength="high",
                 timeframe="2026-05")
    i2 = led.add(module="market", claim="genre flat", value="-0.03",
                 source="romonitor", source_type="external", strength="med")
    assert i1 == "L1" and i2 == "L2"
    assert led.get("L1").claim == "dau -25%"
    assert len(led.all()) == 2


def test_by_ids():
    led = EvidenceLedger()
    led.add(module="m", claim="c", value="v", source="s",
            source_type="derived", strength="low")
    assert [e.id for e in led.by_ids(["L1", "Lx"])] == ["L1"]


def test_load_restores_entries_and_continues_sequence():
    """load() restores persisted entries; subsequent add() gets the next id."""
    led = EvidenceLedger()
    # Simulate two entries that were previously persisted
    persisted = [
        {"id": "L1", "module": "anomaly", "claim": "dau fell", "value": "-0.25",
         "source": "internal:dau", "source_type": "internal", "strength": "high",
         "timeframe": "2026-05"},
        {"id": "L2", "module": "market", "claim": "genre flat", "value": "-0.03",
         "source": "romonitor", "source_type": "external", "strength": "med",
         "timeframe": None},
    ]
    led.load(persisted)

    entries = led.all()
    assert len(entries) == 2
    assert entries[0].id == "L1"
    assert entries[0].claim == "dau fell"
    assert entries[1].id == "L2"

    # add() must continue from L3
    new_id = led.add(module="segment", claim="region=US drove it", value="ep=0.7",
                     source="internal:segment", source_type="internal", strength="high")
    assert new_id == "L3"
    assert len(led.all()) == 3


def test_add_after_gapped_load_avoids_collision():
    """load() with non-contiguous ids (L1, L3) must not collide on the next add().

    len-based: would produce L3 (collision); max-based: correctly produces L4.
    """
    led = EvidenceLedger()
    gapped = [
        {"id": "L1", "module": "anomaly", "claim": "dau fell", "value": "-0.25",
         "source": "internal:dau", "source_type": "internal", "strength": "high",
         "timeframe": "2026-05"},
        {"id": "L3", "module": "market", "claim": "genre flat", "value": "-0.03",
         "source": "romonitor", "source_type": "external", "strength": "med",
         "timeframe": None},
    ]
    led.load(gapped)

    new_id = led.add(module="segment", claim="region=US drove it", value="ep=0.7",
                     source="internal:segment", source_type="internal", strength="high")
    assert new_id == "L4", f"expected L4 (max-based), got {new_id!r}"
