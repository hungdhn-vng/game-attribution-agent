import os


def make_checkpointer():
    """AgentBase Memory checkpointer when MEMORY_ID is set; else in-process MemorySaver."""
    memory_id = os.environ.get("MEMORY_ID", "")
    if memory_id:
        from greennode_agent_bridge import AgentBaseMemoryEvents
        return AgentBaseMemoryEvents(memory_id=memory_id)
    from langgraph.checkpoint.memory import MemorySaver
    return MemorySaver()
