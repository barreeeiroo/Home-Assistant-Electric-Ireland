"""Contract-based assertion helpers for statistics invariant verification.

These helpers encode mathematical invariants and HA recorder contracts.
They do NOT reference coordinator internals — only the recorder output format.

Statistics entries have fields: start (float timestamp), state (float), sum (float).
"""

from __future__ import annotations


def assert_cumulative_sums_monotonic(stats: list[dict]) -> None:
    """Every sum[i] >= sum[i-1] (cumulative sums never decrease for non-negative consumption).

    Raises AssertionError with the index and values if violated.
    """
    for i in range(1, len(stats)):
        prev_sum = stats[i - 1].get("sum") or 0.0
        curr_sum = stats[i].get("sum") or 0.0
        assert curr_sum >= prev_sum - 1e-9, (
            f"Cumulative sum decreased at index {i}: sum[{i - 1}]={prev_sum:.6f} > sum[{i}]={curr_sum:.6f}"
        )


def assert_state_sum_consistency(stats: list[dict]) -> None:
    """sum[i] == sum[i-1] + state[i] (each state value is the delta producing the sum).

    Uses tolerance of 1e-6 for floating-point comparison.
    Raises AssertionError if any entry violates this invariant.
    """
    prev_sum = 0.0
    for i, entry in enumerate(stats):
        state = entry.get("state") or 0.0
        current_sum = entry.get("sum") or 0.0
        expected_sum = prev_sum + state
        assert abs(current_sum - expected_sum) < 1e-6, (
            f"State/sum inconsistency at index {i}: "
            f"prev_sum={prev_sum:.6f} + state={state:.6f} = {expected_sum:.6f} "
            f"but sum={current_sum:.6f} (diff={abs(current_sum - expected_sum):.2e})"
        )
        prev_sum = current_sum


def assert_hour_aligned(stats: list[dict]) -> None:
    """Every start timestamp must be at minute=0, second=0 (hour-aligned).

    The 'start' field is a Unix timestamp (float). Convert to datetime to check alignment.
    Raises AssertionError if any entry is not aligned to the hour.
    """
    from datetime import UTC, datetime

    for i, entry in enumerate(stats):
        start = entry.get("start")
        if start is None:
            continue
        # start may be a datetime object or a Unix timestamp
        if isinstance(start, (int, float)):
            dt = datetime.fromtimestamp(start, tz=UTC)
        else:
            dt = start if start.tzinfo else start.replace(tzinfo=UTC)
        assert dt.minute == 0 and dt.second == 0 and dt.microsecond == 0, (
            f"Entry {i} is not hour-aligned: {dt.isoformat()} (minute={dt.minute}, second={dt.second})"
        )


def assert_conservation(stats: list[dict], input_values: list[float], tolerance: float = 0.01) -> None:
    """Final sum equals sum of input values (energy conservation law).

    Raises AssertionError if |final_sum - sum(input_values)| > tolerance.
    """
    if not stats:
        return
    final_sum = stats[-1].get("sum") or 0.0
    expected_total = sum(input_values)
    assert abs(final_sum - expected_total) <= tolerance, (
        f"Energy conservation violated: "
        f"expected final sum={expected_total:.6f}, "
        f"got final sum={final_sum:.6f} "
        f"(diff={abs(final_sum - expected_total):.6f}, tolerance={tolerance})"
    )


def assert_no_duplicate_hours(stats: list[dict]) -> None:
    """No two statistics entries have the same start timestamp.

    Raises AssertionError listing the duplicate timestamps if any found.
    """
    seen: set = set()
    duplicates: list = []
    for entry in stats:
        start = entry.get("start")
        if start in seen:
            duplicates.append(start)
        else:
            seen.add(start)
    assert not duplicates, f"Duplicate hour entries found: {duplicates}"


def assert_statistic_id_format(stat_id: str, domain: str, account: str, metric: str) -> None:
    """Validates '{domain}:{account}_{metric}' format for a statistic ID.

    Raises AssertionError if the format does not match.
    """
    expected = f"{domain}:{account}_{metric}"
    assert stat_id == expected, f"Statistic ID format error: expected {expected!r}, got {stat_id!r}"
