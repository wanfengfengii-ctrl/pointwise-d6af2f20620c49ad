import sqlite3

from .decision_store import Decision, SuccessReceipt, load_decision


def read(center: sqlite3.Connection, report_id: int) -> tuple[Decision, SuccessReceipt]:
    result = load_decision(center, report_id)
    if result is None:
        raise LookupError(f'unknown report {report_id}')
    return result
