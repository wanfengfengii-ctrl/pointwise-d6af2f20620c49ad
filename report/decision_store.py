import json
import sqlite3
from dataclasses import dataclass
from fractions import Fraction

from catalog.requests import SamplingRequest

POINT_KIND = 'point'
BOUNDS_KIND = 'bounds'


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
class BoundsDecision:
    report_id: int
    request: SamplingRequest
    parents: tuple[ParentPiece, ParentPiece]
    lower: Fraction
    upper: Fraction
    lower_witness: tuple
    upper_witness: tuple
    verdict: str


@dataclass(frozen=True)
class SuccessReceipt:
    success_id: int
    report_id: int


def initialize_decisions(center: sqlite3.Connection) -> None:
    center.execute('PRAGMA foreign_keys = ON')
    center.execute('''
        CREATE TABLE IF NOT EXISTS decisions (
            report_id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL DEFAULT 'point',
            request_snapshot TEXT NOT NULL,
            ordered_parents TEXT NOT NULL,
            probability TEXT,
            lower_bound TEXT,
            upper_bound TEXT,
            lower_witness TEXT,
            upper_witness TEXT,
            verdict TEXT NOT NULL CHECK (verdict IN ('pass', 'retest'))
        )
    ''')
    center.execute('''
        CREATE TABLE IF NOT EXISTS success_receipts (
            success_id INTEGER PRIMARY KEY,
            report_id INTEGER NOT NULL UNIQUE REFERENCES decisions (report_id)
        )
    ''')
    columns = {row[1] for row in center.execute('PRAGMA table_info(decisions)')}
    missing = [
        ('kind', "TEXT NOT NULL DEFAULT 'point'"),
        ('lower_bound', 'TEXT'),
        ('upper_bound', 'TEXT'),
        ('lower_witness', 'TEXT'),
        ('upper_witness', 'TEXT'),
    ]
    needs_rebuild = any(name not in columns for name, _ in missing)
    probability_not_null = next(
        (row[3] for row in center.execute('PRAGMA table_info(decisions)')
         if row[1] == 'probability'), 0,
    )
    if needs_rebuild or probability_not_null:
        # Legacy V1 schemas lack the interval columns and/or require a point
        # probability. Rebuild with foreign keys parked so the existing
        # success_receipts foreign key survives the table replacement.
        center.commit()
        center.execute('PRAGMA foreign_keys = OFF')
        try:
            with center:
                center.execute('ALTER TABLE decisions RENAME TO decisions_legacy')
                center.execute('''
                    CREATE TABLE decisions (
                        report_id INTEGER PRIMARY KEY,
                        kind TEXT NOT NULL DEFAULT 'point',
                        request_snapshot TEXT NOT NULL,
                        ordered_parents TEXT NOT NULL,
                        probability TEXT,
                        lower_bound TEXT,
                        upper_bound TEXT,
                        lower_witness TEXT,
                        upper_witness TEXT,
                        verdict TEXT NOT NULL CHECK (verdict IN ('pass', 'retest'))
                    )
                ''')
                center.execute('''
                    INSERT INTO decisions
                        (report_id, kind, request_snapshot, ordered_parents, probability,
                         lower_bound, upper_bound, lower_witness, upper_witness, verdict)
                    SELECT report_id, 'point', request_snapshot, ordered_parents, probability,
                           NULL, NULL, NULL, NULL, verdict
                    FROM decisions_legacy
                ''')
                center.execute('DROP TABLE decisions_legacy')
        finally:
            center.execute('PRAGMA foreign_keys = ON')


def _request_snapshot(request: SamplingRequest) -> str:
    return json.dumps((request.round_id, request.entry, request.targets, str(request.threshold)))


def _parents_snapshot(parents) -> str:
    return json.dumps([
        (parent.receipt_id, parent.issuance_id, parent.station, parent.revision_id)
        for parent in parents
    ])


def _witness_snapshot(witness) -> str:
    return json.dumps([
        [[list(blocks), [mass.numerator, mass.denominator]] for blocks, mass in station]
        for station in witness
    ])


def _load_witness(payload: str):
    return tuple(
        tuple(
            (tuple(tuple(block) for block in blocks), Fraction(*mass))
            for blocks, mass in station
        )
        for station in json.loads(payload)
    )


def _load_request(row_payload: str) -> SamplingRequest:
    round_id, entry, targets, threshold = json.loads(row_payload)
    return SamplingRequest(round_id, entry, tuple(targets), Fraction(threshold))


def _load_parents(payload: str) -> tuple[ParentPiece, ...]:
    return tuple(ParentPiece(*parent) for parent in json.loads(payload))


def commit_decision(
    center: sqlite3.Connection,
    request: SamplingRequest,
    parents: tuple[ParentPiece, ParentPiece],
    probability: Fraction,
    verdict: str,
) -> tuple[Decision, SuccessReceipt]:
    center.execute('BEGIN IMMEDIATE')
    with center:
        report_id = center.execute('''
            INSERT INTO decisions
                (kind, request_snapshot, ordered_parents, probability,
                 lower_bound, upper_bound, lower_witness, upper_witness, verdict)
            VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL, ?)
        ''', (POINT_KIND, _request_snapshot(request), _parents_snapshot(parents),
              str(probability), verdict)).lastrowid
        success_id = center.execute(
            'INSERT INTO success_receipts (report_id) VALUES (?)', (report_id,),
        ).lastrowid
    return Decision(report_id, request, parents, probability, verdict), SuccessReceipt(success_id, report_id)


def commit_bounds_decision(
    center: sqlite3.Connection,
    request: SamplingRequest,
    parents: tuple[ParentPiece, ParentPiece],
    lower: Fraction,
    upper: Fraction,
    lower_witness,
    upper_witness,
    verdict: str,
) -> tuple[BoundsDecision, SuccessReceipt]:
    center.execute('BEGIN IMMEDIATE')
    with center:
        report_id = center.execute('''
            INSERT INTO decisions
                (kind, request_snapshot, ordered_parents, probability,
                 lower_bound, upper_bound, lower_witness, upper_witness, verdict)
            VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)
        ''', (
            BOUNDS_KIND, _request_snapshot(request), _parents_snapshot(parents),
            str(lower), str(upper),
            _witness_snapshot(lower_witness), _witness_snapshot(upper_witness), verdict,
        )).lastrowid
        success_id = center.execute(
            'INSERT INTO success_receipts (report_id) VALUES (?)', (report_id,),
        ).lastrowid
    decision = BoundsDecision(
        report_id, request, parents, lower, upper, lower_witness, upper_witness, verdict,
    )
    return decision, SuccessReceipt(success_id, report_id)


def load_decision(center: sqlite3.Connection, report_id: int):
    if type(report_id) is not int or not 1 <= report_id < 2**63:
        raise ValueError('report id must be a positive SQLite integer')
    row = center.execute('''
        SELECT d.kind, d.request_snapshot, d.ordered_parents, d.probability,
               d.lower_bound, d.upper_bound, d.lower_witness, d.upper_witness,
               d.verdict, r.success_id
        FROM decisions AS d JOIN success_receipts AS r USING (report_id)
        WHERE d.report_id = ?
    ''', (report_id,)).fetchone()
    if row is None:
        return None
    (kind, request_snapshot, ordered_parents, probability,
     lower_bound, upper_bound, lower_witness, upper_witness, verdict, success_id) = row
    request = _load_request(request_snapshot)
    parents = _load_parents(ordered_parents)
    receipt = SuccessReceipt(success_id, report_id)
    if kind == POINT_KIND:
        return Decision(report_id, request, parents, Fraction(probability), verdict), receipt
    if kind == BOUNDS_KIND:
        decision = BoundsDecision(
            report_id, request, parents,
            Fraction(lower_bound), Fraction(upper_bound),
            _load_witness(lower_witness), _load_witness(upper_witness), verdict,
        )
        return decision, receipt
    raise ValueError(f'unknown decision kind {kind!r}')
