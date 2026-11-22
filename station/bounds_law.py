from collections import defaultdict
from fractions import Fraction

from catalog.ports import PortRoster
from observations.circuits import live_edges
from observations.revisions import BoundsRevision
from .bounds_exchange import BoundsEvidenceRow
from .connectivity import project_public_partition
from .exchange import Partition


def build_bounds_law(
    roster: PortRoster, revision: BoundsRevision,
) -> tuple[BoundsEvidenceRow, ...]:
    """Merge original circuits that realize the same public partition.

    The resulting per-partition interval is exactly the range of total mass
    the original observations can assign to that partition while staying
    inside their own closed intervals.
    """
    segments = {segment.name: segment for segment in revision.segments}
    lower: dict[Partition, Fraction] = defaultdict(Fraction)
    upper: dict[Partition, Fraction] = defaultdict(Fraction)
    for circuit in revision.circuits:
        blocks = project_public_partition(roster.ports, live_edges(segments, circuit))
        lower[blocks] += circuit.lower
        upper[blocks] += circuit.upper
    return tuple(
        BoundsEvidenceRow(blocks, lower[blocks], upper[blocks])
        for blocks in sorted(lower)
        if upper[blocks] > 0
    )
