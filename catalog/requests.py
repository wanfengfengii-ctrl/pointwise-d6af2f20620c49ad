from dataclasses import dataclass
from fractions import Fraction

from .junctions import junction_key, round_junctions
from .ports import require_name
from .trial_store import TrialRecord


@dataclass(frozen=True)
class SamplingRequest:
    round_id: str
    entry: str
    targets: tuple[str, str]
    threshold: Fraction


def validate_request(
    trial: TrialRecord,
    entry: str,
    targets: tuple[str, str] | list[str],
    threshold: Fraction | int | str,
) -> SamplingRequest:
    require_name(entry, 'entry')
    if not isinstance(targets, (tuple, list)) or len(targets) != 2:
        raise ValueError('exactly two target branches are required')
    first, second = (require_name(target, 'target') for target in targets)
    if first == second:
        raise ValueError('target branches must be different')
    public = round_junctions(trial)
    if any(junction_key(trial.round_id, port) not in public for port in (entry, first, second)):
        raise ValueError('entry and targets must be public ports of the selected round')
    if isinstance(threshold, bool) or not isinstance(threshold, (Fraction, int, str)):
        raise ValueError('threshold must be an exact rational number')
    try:
        line = Fraction(threshold)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError('threshold must be an exact rational number') from error
    if not 0 <= line <= 1:
        raise ValueError('threshold must be between zero and one')
    return SamplingRequest(trial.round_id, entry, (first, second), line)
