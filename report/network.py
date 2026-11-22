from collections.abc import Iterator

from catalog.junctions import Junction, junction_key
from catalog.requests import SamplingRequest
from station.connectivity import connected_components
from station.exchange import Partition


def _connections(round_id: str, partition: Partition) -> Iterator[tuple[Junction, Junction]]:
    for block in partition:
        anchor = junction_key(round_id, block[0])
        for port in block[1:]:
            yield anchor, junction_key(round_id, port)


def both_targets_reachable(request: SamplingRequest, first: Partition, second: Partition) -> bool:
    entry = junction_key(request.round_id, request.entry)
    targets = {junction_key(request.round_id, target) for target in request.targets}
    edges = [*_connections(request.round_id, first), *_connections(request.round_id, second)]
    components = connected_components(targets | {entry}, edges)
    entry_component = next(component for component in components if entry in component)
    return targets <= entry_component
