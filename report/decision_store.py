import json
import sqlite3
from dataclasses import dataclass
from fractions import Fraction

from catalog.requests import SamplingRequest


@dataclass(frozen=True)
class ParentPiece:
    receipt_id: int
    issuance_id: str
    station: str
    revision_id: int


@dataclass(frozen=True)
class Decision:
    report_id: int
    request: SamplingRequest
    parents: tuple[ParentPiece, ParentPiece]
    probability: Fraction
    verdict: str


@dataclass(frozen=True)
class SuccessReceipt:
    success_id: int
    report_id: int


def initialize_decisions(center: sqlite3.Connection) -> None:
    center.execute('PRAGMA foreign_keys = ON')
    with center:
        center.execute('''
            CREATE TABLE IF NOT EXISTS decisions (
                report_id INTEGER PRIMARY KEY,
                request_snapshot TEXT NOT NULL,
                ordered_parents TEXT NOT NULL,
                probability TEXT NOT NULL,
                verdict TEXT NOT NULL CHECK (verdict IN ('pass', 'retest'))
            )
        ''')
        center.execute('''
            CREATE TABLE IF NOT EXISTS success_receipts (
                success_id INTEGER PRIMARY KEY,
                report_id INTEGER NOT NULL UNIQUE REFERENCES decisions (report_id)
            )
        ''')


def commit_decision(
    center: sqlite3.Connection,
    request: SamplingRequest,
    parents: tuple[ParentPiece, ParentPiece],
    probability: Fraction,
    verdict: str,
) -> tuple[Decision, SuccessReceipt]:
    request_snapshot = json.dumps((request.round_id, request.entry, request.targets, str(request.threshold)))
    ordered_parents = json.dumps([
        (parent.receipt_id, parent.issuance_id, parent.station, parent.revision_id)
        for parent in parents
    ])
    center.execute('BEGIN IMMEDIATE')
    with center:
        report_id = center.execute('''
            INSERT INTO decisions (request_snapshot, ordered_parents, probability, verdict)
            VALUES (?, ?, ?, ?)
        ''', (request_snapshot, ordered_parents, str(probability), verdict)).lastrowid
        success_id = center.execute(
            'INSERT INTO success_receipts (report_id) VALUES (?)', (report_id,),
        ).lastrowid
    return Decision(report_id, request, parents, probability, verdict), SuccessReceipt(success_id, report_id)


def load_decision(center: sqlite3.Connection, report_id: int) -> tuple[Decision, SuccessReceipt] | None:
    if type(report_id) is not int or not 1 <= report_id < 2**63:
        raise ValueError('report id must be a positive SQLite integer')
    row = center.execute('''
        SELECT d.request_snapshot, d.ordered_parents, d.probability, d.verdict, r.success_id
        FROM decisions AS d JOIN success_receipts AS r USING (report_id)
        WHERE d.report_id = ?
    ''', (report_id,)).fetchone()
    if row is None:
        return None
    request_snapshot, ordered_parents, probability, verdict, success_id = row
    round_id, entry, targets, threshold = json.loads(request_snapshot)
    first_target, second_target = targets
    first_parent, second_parent = (ParentPiece(*parent) for parent in json.loads(ordered_parents))
    request = SamplingRequest(round_id, entry, (first_target, second_target), Fraction(threshold))
    decision = Decision(report_id, request, (first_parent, second_parent), Fraction(probability), verdict)
    return decision, SuccessReceipt(success_id, report_id)
