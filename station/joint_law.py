from collections import defaultdict
from fractions import Fraction

from catalog.ports import PortRoster
from observations.circuits import live_edges
from observations.revisions import Revision
from .connectivity import project_public_partition
from .exchange import EvidenceRow, Partition


def build_joint_law(roster: PortRoster, revision: Revision) -> tuple[EvidenceRow, ...]:
    segments = {segment.name: segment for segment in revision.segments}
    masses: dict[Partition, Fraction] = defaultdict(Fraction)
    for circuit in revision.circuits:
        if circuit.mass == 0:
            continue
        blocks = project_public_partition(roster.ports, live_edges(segments, circuit))
        masses[blocks] += circuit.mass
    return tuple(EvidenceRow(blocks, masses[blocks]) for blocks in sorted(masses))
