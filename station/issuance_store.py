import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class IssuedPiece:
    round_id: str
    station: str
    revision_id: int
    issuance_id: str
    payload: str


def initialize_issuance(source: sqlite3.Connection) -> None:
    source.execute('PRAGMA foreign_keys = ON')
    with source:
        source.execute('''
            CREATE TABLE IF NOT EXISTS issued_pieces (
                round_id TEXT NOT NULL,
                station TEXT NOT NULL,
                revision_id INTEGER NOT NULL,
                issuance_id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL,
                PRIMARY KEY (round_id, station, revision_id),
                FOREIGN KEY (round_id, station, revision_id)
                    REFERENCES revisions (round_id, station, revision_id)
            )
        ''')


def load_issued_piece(
    source: sqlite3.Connection, round_id: str, station: str, revision_id: int,
) -> IssuedPiece | None:
    row = source.execute('''
        SELECT issuance_id, payload FROM issued_pieces
        WHERE round_id = ? AND station = ? AND revision_id = ?
    ''', (round_id, station, revision_id)).fetchone()
    if row is None:
        return None
    return IssuedPiece(round_id, station, revision_id, *row)


def save_issued_piece(source: sqlite3.Connection, issued: IssuedPiece) -> IssuedPiece:
    with source:
        source.execute('''
            INSERT OR IGNORE INTO issued_pieces (round_id, station, revision_id, issuance_id, payload)
            VALUES (?, ?, ?, ?, ?)
        ''', (issued.round_id, issued.station, issued.revision_id, issued.issuance_id, issued.payload))
        fixed = load_issued_piece(source, issued.round_id, issued.station, issued.revision_id)
        if fixed is None:
            raise sqlite3.IntegrityError('issuance identity is already bound to a different revision')
    return fixed
