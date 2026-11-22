from collections.abc import Iterable
from fractions import Fraction

from .circuits import BoundsCircuit
from .weights import parse_weight


def build_bounds_circuit(raw: object) -> BoundsCircuit:
    if not isinstance(raw, (tuple, list)) or len(raw) != 4:
        raise ValueError('each bound circuit must be (observation id, active, lower, upper)')
    observation_id, active, lower, upper = raw
    low = parse_weight(lower)
    high = parse_weight(upper)
    if low > high or high > 1:
        raise ValueError('interval endpoints must satisfy 0 <= lower <= upper <= 1')
    return BoundsCircuit(observation_id, active, low, high)


def validate_unit_interval(circuits: Iterable[BoundsCircuit]) -> None:
    """Reject unless the per-circuit intervals admit weights summing exactly to one."""
    lower_total = Fraction(0)
    upper_total = Fraction(0)
    for circuit in circuits:
        if not isinstance(circuit, BoundsCircuit):
            raise ValueError('bounds circuits must carry closed rational intervals')
        lower_total += circuit.lower
        upper_total += circuit.upper
    if not lower_total <= 1 <= upper_total:
        raise ValueError(
            f'interval weights must admit a choice summing to one, got [{lower_total}, {upper_total}]'
        )
