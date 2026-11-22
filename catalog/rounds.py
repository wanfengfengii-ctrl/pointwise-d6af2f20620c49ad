import sqlite3
from collections.abc import Iterable, Mapping

from .ports import build_port_roster, require_name
from .trial_store import TrialRecord, save_trial


def register(
    trials: sqlite3.Connection,
    round_id: str,
    stations: Mapping[str, Iterable[str]],
) -> TrialRecord:
    require_name(round_id, 'round_id')
    if not isinstance(stations, Mapping) or len(stations) != 2:
        raise ValueError('a trial round has exactly two different stations')
    rosters = [build_port_roster(station, ports) for station, ports in stations.items()]
    first, second = sorted(rosters, key=lambda roster: roster.station)
    return save_trial(trials, TrialRecord(round_id, (first, second)))
