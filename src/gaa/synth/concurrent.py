"""Concurrent N-sample synthesis for self-consistency gate (Task A7)."""
from concurrent.futures import ThreadPoolExecutor, as_completed

from gaa.schema.ledger import EvidenceLedger


def sample_concurrently(synth, ledger: EvidenceLedger, query: str, n: int) -> list:
    """Run synth.synthesize(ledger, query) n times in parallel.

    Uses ThreadPoolExecutor(max_workers=n) so each call hits the LLM independently.
    Thread-safe because each call builds its own request objects.

    Args:
        synth: any object with a synthesize(ledger, query) method.
        ledger: the evidence ledger to pass to each synthesize call.
        query: the user query string.
        n: number of parallel samples to draw.

    Returns:
        List of AttributionHypothesis from successful calls (failures are dropped).
        If n <= 1, calls synthesize once directly (no executor) and returns a 1-list.
    """
    if n <= 1:
        return [synth.synthesize(ledger, query)]

    results = []
    with ThreadPoolExecutor(max_workers=n) as executor:
        futures = [executor.submit(synth.synthesize, ledger, query) for _ in range(n)]
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception:
                pass  # drop failing calls
    return results
