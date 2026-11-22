from collections.abc import Iterable
from dataclasses import dataclass

from .circuits import LiveCircuit, PipeSegment, validate_circuits
from .weights import parse_weight, validate_unit_mass


@dataclass(frozen=True)
class Revision:
    round_id: str
    station: str
    revision_id: int | None
    parent_id: int | None
    segments: tuple[PipeSegment, ...]
    circuits: tuple[LiveCircuit, ...]


def validate_parent(round_id: str, station: str, parent: Revision | None) -> None:
    if parent is None:
        return
    if parent.revision_id is None or (parent.round_id, parent.station) != (round_id, station):
        raise LookupError('parent revision must be recorded for the same round and station')


def new_revision(
    round_id: str,
    station: str,
    segments: Iterable[PipeSegment],
    circuits: Iterable[LiveCircuit],
    parent: Revision | None = None,
) -> Revision:
    validate_parent(round_id, station, parent)
    try:
        pipes = tuple(segments)
        observations = tuple(circuits)
    except TypeError as error:
        raise ValueError('segments and circuits must be supplied as collections') from error
    validate_circuits(pipes, observations)
    frozen = tuple(
        LiveCircuit(circuit.observation_id, tuple(sorted(circuit.active)), parse_weight(circuit.mass))
        for circuit in observations
    )
    validate_unit_mass(circuit.mass for circuit in frozen)
    parent_id = None if parent is None else parent.revision_id
    return Revision(round_id, station, None, parent_id, pipes, frozen)
