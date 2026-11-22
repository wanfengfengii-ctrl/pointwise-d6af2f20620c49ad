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


def validate_circuits(
    segments: Iterable[PipeSegment], circuits: Iterable[LiveCircuit],
) -> None:
    names: set[str] = set()
    for segment in segments:
        if not isinstance(segment, PipeSegment):
            raise ValueError('segments must be PipeSegment records')
        name = require_name(segment.name, 'segment name')
        require_name(segment.left, 'left endpoint')
        require_name(segment.right, 'right endpoint')
        if name in names:
            raise ValueError(f'duplicate segment name {name!r}')
        names.add(name)

    observations: set[str] = set()
    for circuit in circuits:
        if not isinstance(circuit, LiveCircuit):
            raise ValueError('circuits must be LiveCircuit records')
        observation_id = require_name(circuit.observation_id, 'observation id')
        if observation_id in observations:
            raise ValueError(f'duplicate observation id {observation_id!r}')
        observations.add(observation_id)
        if not isinstance(circuit.active, (tuple, list, set, frozenset)):
            raise ValueError('active segments must be a collection of names')
        active = tuple(require_name(name, 'active segment') for name in circuit.active)
        if len(set(active)) != len(active):
            raise ValueError(f'duplicate active segment in observation {observation_id!r}')
        unknown = set(active) - names
        if unknown:
            raise ValueError(f'unknown active segments in {observation_id!r}: {sorted(unknown)}')


def live_edges(
    segments: Mapping[str, PipeSegment], circuit: LiveCircuit,
) -> Iterator[tuple[str, str]]:
    for name in circuit.active:
        segment = segments[name]
        yield segment.left, segment.right
