import sqlite3
from fractions import Fraction

from catalog.requests import validate_request
from catalog.trial_store import load_trial
from receipt.identity import ReceiptRecord
from receipt.selection import select_pair
from .decision_store import Decision, ParentPiece, SuccessReceipt, commit_decision
from .probability import joint_supply_probability, passes_threshold


def _parent(receipt: ReceiptRecord) -> ParentPiece:
    piece = receipt.piece
    return ParentPiece(receipt.receipt_id, piece.issuance_id, piece.station, piece.revision_id)


def sign(
    trials: sqlite3.Connection,
    center: sqlite3.Connection,
    receipt_ids: tuple[int, int] | list[int],
    entry: str,
    targets: tuple[str, str] | list[str],
    threshold: Fraction | int | str,
) -> tuple[Decision, SuccessReceipt]:
    pair = select_pair(center, receipt_ids)
    request = validate_request(load_trial(trials, pair.round_id), entry, targets, threshold)
    probability = joint_supply_probability(pair, request)
    verdict = 'pass' if passes_threshold(probability, request) else 'retest'
    parents = _parent(pair.first), _parent(pair.second)
    return commit_decision(center, request, parents, probability, verdict)
