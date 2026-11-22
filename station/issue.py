import sqlite3

from catalog.trial_store import load_trial
from observations.revision_store import load_revision
from .exchange import StationPiece, encode_piece, issuance_identity
from .issuance_store import IssuedPiece, load_issued_piece, save_issued_piece
from .joint_law import build_joint_law


def issue(
    trials: sqlite3.Connection,
    source: sqlite3.Connection,
    round_id: str,
    station: str,
    revision_id: int,
) -> IssuedPiece:
    roster = load_trial(trials, round_id).roster(station)
    if type(revision_id) is not int or not 1 <= revision_id < 2**63:
        raise ValueError('revision id must be a positive SQLite integer')
    fixed = load_issued_piece(source, round_id, station, revision_id)
    if fixed is not None:
        return fixed

    revision = load_revision(source, round_id, station, revision_id)
    issuance_id = issuance_identity(round_id, station, revision_id)
    piece = StationPiece(
        issuance_id, round_id, station, revision_id, roster.ports, build_joint_law(roster, revision),
    )
    return save_issued_piece(source, IssuedPiece(
        round_id, station, revision_id, issuance_id, encode_piece(piece),
    ))
