from gaa.memory import make_checkpointer


def test_local_checkpointer_when_no_memory_id(monkeypatch):
    monkeypatch.delenv("MEMORY_ID", raising=False)
    cp = make_checkpointer()
    from langgraph.checkpoint.memory import MemorySaver
    assert isinstance(cp, MemorySaver)
