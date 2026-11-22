from fractions import Fraction

from catalog.trial_store import TrialRecord
from station.bounds_exchange import BoundsStationPiece, bounds_issuance_identity
from station.exchange import EvidenceRow, issuance_identity


def validate_partition_structure(ports: tuple[str, ...], partition, context: str) -> None:
    if any(not block or block != tuple(sorted(block)) for block in partition):
        raise ValueError(f'{context} partition blocks must be nonempty and sorted')
    if partition != tuple(sorted(partition)):
        raise ValueError(f'{context} partition blocks are out of order')
    flattened = tuple(sorted(port for block in partition for port in block))
    if flattened != ports:
        raise ValueError(f'{context} partition must cover each public port exactly once')


def validate_joint_rows(ports: tuple[str, ...], rows: tuple[EvidenceRow, ...]) -> None:
    previous = None
    total = Fraction(0)
    for row in rows:
        partition = row.blocks
        validate_partition_structure(ports, partition, 'evidence')
        if previous is not None and partition <= previous:
            raise ValueError('evidence partitions must be distinct and sorted')
        if row.mass < 0:
            raise ValueError('partition mass must be nonnegative')
        previous = partition
        total += row.mass
    if total != 1:
        raise ValueError('partition masses must sum to one')


def validate_bounds_rows(ports: tuple[str, ...], rows) -> None:
    previous = None
    lower_total = Fraction(0)
    upper_total = Fraction(0)
    for row in rows:
        partition = row.blocks
        validate_partition_structure(ports, partition, 'interval evidence')
        if previous is not None and partition <= previous:
            raise ValueError('evidence partitions must be distinct and sorted')
        if row.lower < 0 or row.lower > row.upper or row.upper > 1:
            raise ValueError('partition intervals must satisfy 0 <= lower <= upper <= 1')
        previous = partition
        lower_total += row.lower
        upper_total += row.upper
    if not lower_total <= 1 <= upper_total:
        raise ValueError('partition intervals must admit a distribution summing to one')


def validate_piece(trial: TrialRecord, piece) -> None:
    if trial.round_id != piece.round_id:
        raise ValueError('station piece belongs to a different trial round')
    roster = trial.roster(piece.station)
    if piece.ports != roster.ports:
        raise ValueError('station piece ports must match the fixed roster')
    if isinstance(piece, BoundsStationPiece):
        if piece.issuance_id != bounds_issuance_identity(piece.round_id, piece.station, piece.revision_id):
            raise ValueError('issuance identity does not match the round, station and revision')
        validate_bounds_rows(roster.ports, piece.rows)
        return
    if piece.issuance_id != issuance_identity(piece.round_id, piece.station, piece.revision_id):
        raise ValueError('issuance identity does not match the round, station and revision')
    validate_joint_rows(roster.ports, piece.rows)
