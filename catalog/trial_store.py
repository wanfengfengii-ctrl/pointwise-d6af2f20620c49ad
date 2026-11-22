import json
import sqlite3
from dataclasses import dataclass

from .ports import PortRoster, require_name


@dataclass(frozen=True)
class TrialRecord:
    round_id: str
    rosters: tuple[PortRoster, PortRoster]

    def roster(self, station: str) -> PortRoster:
        require_name(station, 'station')
        for roster in self.rosters:
            if roster.station == station:
                return roster
        raise LookupError(f'unregistered station {station!r} in round {self.round_id!r}')


def initialize_trials(trials: sqlite3.Connection) -> None:
    with trials:
        trials.execute('''
            CREATE TABLE IF NOT EXISTS trials (
                round_id TEXT PRIMARY KEY NOT NULL,
                rosters TEXT NOT NULL
            )
        ''')


def save_trial(trials: sqlite3.Connection, record: TrialRecord) -> TrialRecord:
    payload = json.dumps([(r.station, r.ports) for r in record.rosters])
    with trials:
        trials.execute(
            'INSERT OR IGNORE INTO trials (round_id, rosters) VALUES (?, ?)',
            (record.round_id, payload),
        )
        fixed = load_trial(trials, record.round_id)
        if fixed != record:
            raise ValueError(f'conflicting roster for round {record.round_id!r}')
    return fixed


def load_trial(trials: sqlite3.Connection, round_id: str) -> TrialRecord:
    require_name(round_id, 'round_id')
    row = trials.execute(
        'SELECT rosters FROM trials WHERE round_id = ?', (round_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f'unknown trial round {round_id!r}')
    first, second = json.loads(row[0])
    return TrialRecord(round_id, (
        PortRoster(first[0], tuple(first[1])),
        PortRoster(second[0], tuple(second[1])),
    ))
