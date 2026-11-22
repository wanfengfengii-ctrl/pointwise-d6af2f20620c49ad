import json
import sqlite3
from dataclasses import replace
from fractions import Fraction

from .circuits import BoundsCircuit, LiveCircuit, PipeSegment
from .revisions import BoundsRevision, Revision

POINT_KIND = 'point'
BOUNDS_KIND = 'bounds'


def initialize_revisions(source: sqlite3.Connection) -> None:
    source.execute('PRAGMA foreign_keys = ON')
    with source:
        source.execute('''
            CREATE TABLE IF NOT EXISTS revisions (
                revision_id INTEGER PRIMARY KEY,
                round_id TEXT NOT NULL,
                station TEXT NOT NULL,
                parent_id INTEGER,
                kind TEXT NOT NULL DEFAULT 'point',
                original_observations TEXT NOT NULL,
                UNIQUE (round_id, station, revision_id),
                FOREIGN KEY (round_id, station, parent_id)
                    REFERENCES revisions (round_id, station, revision_id)
            )
        ''')
        columns = {row[1] for row in source.execute('PRAGMA table_info(revisions)')}
        if 'kind' not in columns:
            source.execute("ALTER TABLE revisions ADD COLUMN kind TEXT NOT NULL DEFAULT 'point'")


def _snapshot(revision) -> tuple[str, str]:
    if isinstance(revision, BoundsRevision):
        kind = BOUNDS_KIND
        circuits = [
            (circuit.observation_id, circuit.active,
             [circuit.lower.numerator, circuit.lower.denominator],
             [circuit.upper.numerator, circuit.upper.denominator])
            for circuit in revision.circuits
        ]
    elif isinstance(revision, Revision):
        kind = POINT_KIND
        circuits = [
            (circuit.observation_id, circuit.active, [circuit.mass.numerator, circuit.mass.denominator])
            for circuit in revision.circuits
        ]
    else:
        raise ValueError('unsupported revision record')
    observations = {
        'segments': [(pipe.name, pipe.left, pipe.right) for pipe in revision.segments],
        'circuits': circuits,
    }
    return kind, json.dumps(observations)


def store_revision(source: sqlite3.Connection, revision) -> object:
    if revision.revision_id is not None:
        raise ValueError('a stored revision cannot be inserted again')
    kind, payload = _snapshot(revision)
    with source:
        cursor = source.execute('''
            INSERT INTO revisions (round_id, station, parent_id, kind, original_observations)
            VALUES (?, ?, ?, ?, ?)
        ''', (revision.round_id, revision.station, revision.parent_id, kind, payload))
        fixed = replace(revision, revision_id=cursor.lastrowid)
    return fixed


def _load_row(source: sqlite3.Connection, round_id: str, station: str, revision_id: int):
    if type(revision_id) is not int or not 1 <= revision_id < 2**63:
        raise ValueError('revision id must be a positive SQLite integer')
    row = source.execute('''
        SELECT parent_id, kind, original_observations FROM revisions
        WHERE round_id = ? AND station = ? AND revision_id = ?
    ''', (round_id, station, revision_id)).fetchone()
    if row is None:
        raise LookupError(f'unknown revision {revision_id} for {round_id!r} / {station!r}')
    return row


def _decode(kind: str, payload: str, round_id: str, station: str, revision_id: int, parent_id):
    observations = json.loads(payload)
    segments = tuple(PipeSegment(*segment) for segment in observations['segments'])
    if kind == POINT_KIND:
        circuits = tuple(
            LiveCircuit(observation_id, tuple(active), Fraction(*mass))
            for observation_id, active, mass in observations['circuits']
        )
        return Revision(round_id, station, revision_id, parent_id, segments, circuits)
    if kind == BOUNDS_KIND:
        circuits = tuple(
            BoundsCircuit(observation_id, tuple(active), Fraction(*lower), Fraction(*upper))
            for observation_id, active, lower, upper in observations['circuits']
        )
        return BoundsRevision(round_id, station, revision_id, parent_id, segments, circuits)
    raise ValueError(f'unknown revision kind {kind!r}')


def load_revision(
    source: sqlite3.Connection, round_id: str, station: str, revision_id: int,
) -> Revision:
    parent_id, kind, payload = _load_row(source, round_id, station, revision_id)
    if kind != POINT_KIND:
        raise LookupError(f'revision {revision_id} is not a point-weight revision')
    return _decode(kind, payload, round_id, station, revision_id, parent_id)


def load_bounds_revision(
    source: sqlite3.Connection, round_id: str, station: str, revision_id: int,
) -> BoundsRevision:
    parent_id, kind, payload = _load_row(source, round_id, station, revision_id)
    if kind != BOUNDS_KIND:
        raise LookupError(f'revision {revision_id} is not an interval revision')
    return _decode(kind, payload, round_id, station, revision_id, parent_id)


def load_any_revision(
    source: sqlite3.Connection, round_id: str, station: str, revision_id: int,
):
    parent_id, kind, payload = _load_row(source, round_id, station, revision_id)
    return _decode(kind, payload, round_id, station, revision_id, parent_id)
