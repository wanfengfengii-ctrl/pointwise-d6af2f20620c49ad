from .trial_store import TrialRecord

Junction = tuple[str, str]


def junction_key(round_id: str, port: str) -> Junction:
    return round_id, port


def round_junctions(trial: TrialRecord) -> frozenset[Junction]:
    return frozenset(
        junction_key(trial.round_id, port)
        for roster in trial.rosters
        for port in roster.ports
    )
