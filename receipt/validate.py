from fractions import Fraction

from catalog.trial_store import TrialRecord
from station.exchange import EvidenceRow, StationPiece, issuance_identity


def validate_joint_rows(ports: tuple[str, ...], rows: tuple[EvidenceRow, ...]) -> None:
    previous = None
    total = Fraction(0)
    for row in rows:
        partition = row.blocks
        if any(not block or block != tuple(sorted(block)) for block in partition):
            raise ValueError('partition blocks must be nonempty and sorted')
        if partition != tuple(sorted(partition)):
            raise ValueError('partition blocks are out of order')
        flattened = tuple(sorted(port for block in partition for port in block))
        if flattened != ports:
            raise ValueError('partition must cover each public port exactly once')
        if previous is not None and partition <= previous:
            raise ValueError('evidence partitions must be distinct and sorted')
        if row.mass < 0:
            raise ValueError('partition mass must be nonnegative')
        previous = partition
        total += row.mass
    if total != 1:
        raise ValueError('partition masses must sum to one')


def validate_piece(trial: TrialRecord, piece: StationPiece) -> None:
    if trial.round_id != piece.round_id:
        raise ValueError('station piece belongs to a different trial round')
    roster = trial.roster(piece.station)
    if piece.ports != roster.ports:
        raise ValueError('station piece ports must match the fixed roster')
    if piece.issuance_id != issuance_identity(piece.round_id, piece.station, piece.revision_id):
        raise ValueError('issuance identity does not match the round, station and revision')
    validate_joint_rows(roster.ports, piece.rows)
