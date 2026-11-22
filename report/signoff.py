import sqlite3

from catalog.requests import validate_request
from catalog.trial_store import load_trial
from receipt.identity import ReceiptRecord
from receipt.selection import select_pair
from station.bounds_exchange import BoundsStationPiece
from .bounds import back_substitute, bounds_supply_extrema
from .decision_store import (
    BoundsDecision,
    Decision,
    ParentPiece,
    SuccessReceipt,
    commit_bounds_decision,
    commit_decision,
)
from .probability import joint_supply_probability, passes_threshold


def _parent(receipt: ReceiptRecord) -> ParentPiece:
    piece = receipt.piece
    return ParentPiece(receipt.receipt_id, piece.issuance_id, piece.station, piece.revision_id)


def _require_point(pair) -> None:
    if any(isinstance(receipt.piece, BoundsStationPiece)
           for receipt in (pair.first, pair.second)):
        raise ValueError('report.sign only accepts point-weight station pieces; use sign_bounds')


def sign(
    trials,
    center: sqlite3.Connection,
    receipt_ids,
    entry: str,
    targets,
    threshold,
) -> tuple[Decision, SuccessReceipt]:
    pair = select_pair(center, receipt_ids)
    _require_point(pair)
    request = validate_request(load_trial(trials, pair.round_id), entry, targets, threshold)
    probability = joint_supply_probability(pair, request)
    verdict = 'pass' if passes_threshold(probability, request) else 'retest'
    parents = _parent(pair.first), _parent(pair.second)
    return commit_decision(center, request, parents, probability, verdict)


def sign_bounds(
    trials,
    center: sqlite3.Connection,
    receipt_ids,
    entry: str,
    targets,
    threshold,
) -> tuple[BoundsDecision, SuccessReceipt]:
    pair = select_pair(center, receipt_ids)
    request = validate_request(load_trial(trials, pair.round_id), entry, targets, threshold)
    extrema = bounds_supply_extrema(pair, request)
    lower, upper = extrema['lower'], extrema['upper']
    lower_witness, upper_witness = extrema['lower_witness'], extrema['upper_witness']
    # Every stored witness must reproduce its endpoint exactly.
    if back_substitute(pair, request, lower_witness) != lower:
        raise ValueError('lower bound witness does not reproduce its endpoint')
    if back_substitute(pair, request, upper_witness) != upper:
        raise ValueError('upper bound witness does not reproduce its endpoint')
    verdict = 'pass' if passes_threshold(lower, request) else 'retest'
    parents = _parent(pair.first), _parent(pair.second)
    return commit_bounds_decision(
        center, request, parents, lower, upper, lower_witness, upper_witness, verdict,
    )
