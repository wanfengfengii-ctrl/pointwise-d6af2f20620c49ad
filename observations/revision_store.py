import json
import sqlite3
from dataclasses import replace
from fractions import Fraction

from .circuits import LiveCircuit, PipeSegment
from .revisions import Revision


def initialize_revisions(source: sqlite3.Connection) -> None:
    source.execute('PRAGMA foreign_keys = ON')
    with source:
        source.execute('''
            CREATE TABLE IF NOT EXISTS revisions (
                revision_id INTEGER PRIMARY KEY,
                round_id TEXT NOT NULL,
                station TEXT NOT NULL,
                parent_id INTEGER,
                original_observations TEXT NOT NULL,
                UNIQUE (round_id, station, revision_id),
                FOREIGN KEY (round_id, station, parent_id)
                    REFERENCES revisions (round_id, station, revision_id)
            )
        ''')


def store_revision(source: sqlite3.Connection, revision: Revision) -> Revision:
    if revision.revision_id is not None:
        raise ValueError('a stored revision cannot be inserted again')
    observations = {
        'segments': [(pipe.name, pipe.left, pipe.right) for pipe in revision.segments],
        'circuits': [
            (circuit.observation_id, circuit.active, [circuit.mass.numerator, circuit.mass.denominator])
            for circuit in revision.circuits
        ],
    }
    with source:
        cursor = source.execute('''
            INSERT INTO revisions (round_id, station, parent_id, original_observations)
            VALUES (?, ?, ?, ?)
        ''', (revision.round_id, revision.station, revision.parent_id, json.dumps(observations)))
        fixed = replace(revision, revision_id=cursor.lastrowid)
    return fixed


def load_revision(
    source: sqlite3.Connection, round_id: str, station: str, revision_id: int,
) -> Revision:
    if type(revision_id) is not int or not 1 <= revision_id < 2**63:
        raise ValueError('revision id must be a positive SQLite integer')
    row = source.execute('''
        SELECT parent_id, original_observations FROM revisions
        WHERE round_id = ? AND station = ? AND revision_id = ?
    ''', (round_id, station, revision_id)).fetchone()
    if row is None:
        raise LookupError(f'unknown revision {revision_id} for {round_id!r} / {station!r}')
    parent_id, payload = row
    observations = json.loads(payload)
    return Revision(
        round_id, station, revision_id, parent_id,
        tuple(PipeSegment(*segment) for segment in observations['segments']),
        tuple(
            LiveCircuit(observation_id, tuple(active), Fraction(*mass))
            for observation_id, active, mass in observations['circuits']
        ),
    )
