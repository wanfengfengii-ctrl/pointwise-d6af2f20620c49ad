from collections.abc import Iterable
from dataclasses import dataclass

from .circuits import BoundsCircuit, LiveCircuit, PipeSegment, validate_active, validate_segments
from .interval import build_bounds_circuit, validate_unit_interval
from .weights import parse_weight, validate_unit_mass


@dataclass(frozen=True)
class Revision:
    round_id: str
    station: str
    revision_id: int | None
    parent_id: int | None
    segments: tuple[PipeSegment, ...]
    circuits: tuple[LiveCircuit, ...]


@dataclass(frozen=True)
class BoundsRevision:
    round_id: str
    station: str
    revision_id: int | None
    parent_id: int | None
    segments: tuple[PipeSegment, ...]
    circuits: tuple[BoundsCircuit, ...]


def validate_parent(round_id: str, station: str, parent) -> None:
    if parent is None:
        return
    if parent.revision_id is None or (parent.round_id, parent.station) != (round_id, station):
        raise LookupError('parent revision must be recorded for the same round and station')


def _freeze_pipes(segments: Iterable[PipeSegment]) -> tuple[PipeSegment, ...]:
    try:
        return tuple(segments)
    except TypeError as error:
        raise ValueError('segments and circuits must be supplied as collections') from error


def new_revision(
    round_id: str,
    station: str,
    segments: Iterable[PipeSegment],
    circuits: Iterable[LiveCircuit],
    parent=None,
) -> Revision:
    validate_parent(round_id, station, parent)
    try:
        pipes = tuple(segments)
        observations = tuple(circuits)
    except TypeError as error:
        raise ValueError('segments and circuits must be supplied as collections') from error
    names = validate_segments(pipes)
    frozen_circuits = []
    seen: set[str] = set()
    for circuit in observations:
        if not isinstance(circuit, LiveCircuit):
            raise ValueError('circuits must be LiveCircuit records')
        if circuit.observation_id in seen:
            raise ValueError(f'duplicate observation id {circuit.observation_id!r}')
        seen.add(circuit.observation_id)
        active = validate_active(circuit.observation_id, circuit.active, names)
        frozen_circuits.append(LiveCircuit(circuit.observation_id, active, parse_weight(circuit.mass)))
    validate_unit_mass(circuit.mass for circuit in frozen_circuits)
    parent_id = None if parent is None else parent.revision_id
    return Revision(round_id, station, None, parent_id, pipes, tuple(frozen_circuits))


def new_bounds_revision(
    round_id: str,
    station: str,
    segments: Iterable[PipeSegment],
    circuits: Iterable[tuple],
    parent=None,
) -> BoundsRevision:
    validate_parent(round_id, station, parent)
    pipes = _freeze_pipes(segments)
    names = validate_segments(pipes)
    try:
        raw_circuits = tuple(circuits)
    except TypeError as error:
        raise ValueError('segments and circuits must be supplied as collections') from error
    bounds = tuple(build_bounds_circuit(raw) for raw in raw_circuits)
    seen: set[str] = set()
    frozen_circuits = []
    for circuit in bounds:
        if circuit.observation_id in seen:
            raise ValueError(f'duplicate observation id {circuit.observation_id!r}')
        seen.add(circuit.observation_id)
        active = validate_active(circuit.observation_id, circuit.active, names)
        frozen_circuits.append(BoundsCircuit(circuit.observation_id, active, circuit.lower, circuit.upper))
    validate_unit_interval(frozen_circuits)
    parent_id = None if parent is None else parent.revision_id
    return BoundsRevision(round_id, station, None, parent_id, pipes, tuple(frozen_circuits))
