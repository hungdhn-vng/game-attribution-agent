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
