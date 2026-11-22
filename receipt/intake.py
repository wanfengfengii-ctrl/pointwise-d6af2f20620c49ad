import sqlite3

from catalog.trial_store import load_trial
from station.decode import decode_any
from .identity import ReceiptRecord, check_replay
from .validate import validate_piece


def initialize_receipts(center: sqlite3.Connection) -> None:
    with center:
        center.execute('''
            CREATE TABLE IF NOT EXISTS received_pieces (
                receipt_id INTEGER PRIMARY KEY,
                issuance_id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL
            )
        ''')


def receive(trials: sqlite3.Connection, center: sqlite3.Connection, payload: str) -> int:
    piece = decode_any(payload)
    validate_piece(load_trial(trials, piece.round_id), piece)
    with center:
        cursor = center.execute('''
            INSERT OR IGNORE INTO received_pieces (issuance_id, payload) VALUES (?, ?)
        ''', (piece.issuance_id, payload))
        if cursor.rowcount == 1:
            receipt_id = cursor.lastrowid
        else:
            row = center.execute('''
                SELECT receipt_id, payload FROM received_pieces WHERE issuance_id = ?
            ''', (piece.issuance_id,)).fetchone()
            if row is None:
                raise sqlite3.IntegrityError('station receipt was not stored')
            existing_id, fixed_payload = row
            existing = ReceiptRecord(existing_id, decode_any(fixed_payload), fixed_payload)
            receipt_id = check_replay(existing, piece)
    return receipt_id


def load_receipt(center: sqlite3.Connection, receipt_id: int) -> ReceiptRecord:
    if type(receipt_id) is not int or not 1 <= receipt_id < 2**63:
        raise ValueError('station receipt id must be a positive SQLite integer')
    row = center.execute('SELECT payload FROM received_pieces WHERE receipt_id = ?', (receipt_id,)).fetchone()
    if row is None:
        raise LookupError(f'unknown station receipt {receipt_id}')
    payload = row[0]
    return ReceiptRecord(receipt_id, decode_any(payload), payload)
