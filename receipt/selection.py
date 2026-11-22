import sqlite3
from dataclasses import dataclass

from .identity import ReceiptRecord
from .intake import load_receipt


@dataclass(frozen=True)
class SelectedPair:
    round_id: str
    first: ReceiptRecord
    second: ReceiptRecord


def select_pair(
    center: sqlite3.Connection, receipt_ids: tuple[int, int] | list[int],
) -> SelectedPair:
    if not isinstance(receipt_ids, (tuple, list)) or len(receipt_ids) != 2:
        raise ValueError('exactly two station receipt ids are required')
    first = load_receipt(center, receipt_ids[0])
    second = load_receipt(center, receipt_ids[1])
    if first.piece.round_id != second.piece.round_id:
        raise ValueError('station receipts belong to different trial rounds')
    if first.piece.station == second.piece.station:
        raise ValueError('station receipts must belong to different stations')
    return SelectedPair(first.piece.round_id, first, second)
