from dataclasses import dataclass

from station.exchange import StationPiece


@dataclass(frozen=True)
class ReceiptRecord:
    receipt_id: int
    piece: StationPiece
    payload: str


def check_replay(existing: ReceiptRecord, incoming: StationPiece) -> int:
    if existing.piece != incoming:
        raise ValueError(f'conflicting content for issuance {incoming.issuance_id!r}')
    return existing.receipt_id
