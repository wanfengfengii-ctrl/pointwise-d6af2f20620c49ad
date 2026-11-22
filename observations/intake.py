import sqlite3
from collections.abc import Iterable

from catalog.trial_store import load_trial
from .circuits import LiveCircuit, PipeSegment
from .revision_store import load_revision, store_revision
from .revisions import Revision, new_revision


def ingest(
    trials: sqlite3.Connection,
    source: sqlite3.Connection,
    round_id: str,
    station: str,
    segments: Iterable[PipeSegment],
    circuits: Iterable[LiveCircuit],
    *,
    parent_id: int | None = None,
) -> Revision:
    load_trial(trials, round_id).roster(station)
    parent = None if parent_id is None else load_revision(source, round_id, station, parent_id)
    revision = new_revision(round_id, station, segments, circuits, parent)
    return store_revision(source, revision)
