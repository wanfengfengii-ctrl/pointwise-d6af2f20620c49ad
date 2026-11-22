import sqlite3
from collections.abc import Iterable

from catalog.trial_store import load_trial
from .circuits import LiveCircuit, PipeSegment
from .revision_store import load_any_revision, load_revision, store_revision
from .revisions import BoundsRevision, Revision, new_bounds_revision, new_revision


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


def ingest_bounds(
    trials: sqlite3.Connection,
    source: sqlite3.Connection,
    round_id: str,
    station: str,
    segments: Iterable[PipeSegment],
    circuits: Iterable[tuple],
    *,
    parent_id: int | None = None,
) -> BoundsRevision:
    load_trial(trials, round_id).roster(station)
    parent = None if parent_id is None else load_any_revision(source, round_id, station, parent_id)
    revision = new_bounds_revision(round_id, station, segments, circuits, parent)
    return store_revision(source, revision)
