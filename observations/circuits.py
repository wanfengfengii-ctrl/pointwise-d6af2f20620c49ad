from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import dataclass
from fractions import Fraction

from catalog.ports import require_name


@dataclass(frozen=True)
class PipeSegment:
    name: str
    left: str
    right: str


@dataclass(frozen=True)
class LiveCircuit:
    observation_id: str
    active: Collection[str]
    mass: Fraction | int | str


@dataclass(frozen=True)
class BoundsCircuit:
    observation_id: str
    active: Collection[str]
    lower: Fraction | int | str
    upper: Fraction | int | str


def validate_segments(segments: Iterable[PipeSegment]) -> dict[str, PipeSegment]:
    names: dict[str, PipeSegment] = {}
    for segment in segments:
        if not isinstance(segment, PipeSegment):
            raise ValueError('segments must be PipeSegment records')
        name = require_name(segment.name, 'segment name')
        require_name(segment.left, 'left endpoint')
        require_name(segment.right, 'right endpoint')
        if name in names:
            raise ValueError(f'duplicate segment name {name!r}')
        names[name] = segment
    return names


def validate_active(observation_id: str, active: object, names: Collection[str]) -> tuple[str, ...]:
    if not isinstance(active, (tuple, list, set, frozenset)):
        raise ValueError('active segments must be a collection of names')
    checked = tuple(require_name(name, 'active segment') for name in active)
    if len(set(checked)) != len(checked):
        raise ValueError(f'duplicate active segment in observation {observation_id!r}')
    unknown = set(checked) - set(names)
    if unknown:
        raise ValueError(f'unknown active segments in {observation_id!r}: {sorted(unknown)}')
    return tuple(sorted(checked))


def validate_circuits(
    segments: Iterable[PipeSegment], circuits: Iterable[LiveCircuit],
) -> None:
    names = validate_segments(segments)

    observations: set[str] = set()
    for circuit in circuits:
        if not isinstance(circuit, LiveCircuit):
            raise ValueError('circuits must be LiveCircuit records')
        observation_id = require_name(circuit.observation_id, 'observation id')
        if observation_id in observations:
            raise ValueError(f'duplicate observation id {observation_id!r}')
        observations.add(observation_id)
        validate_active(observation_id, circuit.active, names)


def live_edges(
    segments: Mapping[str, PipeSegment], circuit: LiveCircuit,
) -> Iterator[tuple[str, str]]:
    for name in circuit.active:
        segment = segments[name]
        yield segment.left, segment.right
