from collections.abc import Hashable, Iterable
from typing import TypeVar

Vertex = TypeVar('Vertex', bound=Hashable)


def connected_components(
    vertices: Iterable[Vertex], edges: Iterable[tuple[Vertex, Vertex]],
) -> list[set[Vertex]]:
    adjacency: dict[Vertex, set[Vertex]] = {vertex: set() for vertex in vertices}
    for left, right in edges:
        adjacency.setdefault(left, set()).add(right)
        adjacency.setdefault(right, set()).add(left)

    pending = set(adjacency)
    components = []
    while pending:
        start = pending.pop()
        component = {start}
        stack = [start]
        while stack:
            vertex = stack.pop()
            unseen = adjacency[vertex] & pending
            pending.difference_update(unseen)
            component.update(unseen)
            stack.extend(unseen)
        components.append(component)
    return components


def project_public_partition(
    ports: Iterable[str], edges: Iterable[tuple[str, str]],
) -> tuple[tuple[str, ...], ...]:
    public = set(ports)
    projected = []
    for component in connected_components(public, edges):
        block = public & component
        if block:
            projected.append(tuple(sorted(block)))
    return tuple(sorted(projected))
