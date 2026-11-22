import sys
import sqlite3
from contextlib import closing
from fractions import Fraction
from catalog import initialize_trials, register
from observations import LiveCircuit, PipeSegment, ingest, initialize_revisions
from receipt import initialize_receipts, receive
from report import initialize_decisions, read, sign
from station import initialize_issuance, issue

ROUND = "bounds-01"
ENTRY = "P"
TARGETS = ("A", "B")
ROSTERS = {"north": ("P", "A", "B"), "south": ("P", "A", "B")}
NORTH_PIPES = (
    PipeSegment("feed", "P", "north-private"),
    PipeSegment("pa", "north-private", "A"),
    PipeSegment("pb", "P", "B"),
)
SOUTH_PIPES = (PipeSegment("pa", "P", "A"), PipeSegment("pb", "P", "B"))
NORTH_INTERVALS = (
    ("a-first", ("feed", "pa"), "1/4", "1/2"),
    ("a-second", ("feed", "pa"), "1/4", "1/2"),
    ("b", ("pb",), 0, "1/2"),
)
NORTH_NOMINAL = tuple(
    LiveCircuit(name, active, mass)
    for (name, active, _, _), mass in zip(NORTH_INTERVALS, ("3/8", "3/8", "1/4"), strict=True)
)
NORTH_POINT = tuple((row.observation_id, row.active, row.mass, row.mass) for row in NORTH_NOMINAL)
SOUTH_POINT = (LiveCircuit("b", ("pb",), 1),)
NORTH_HALF = (("a", ("feed", "pa"), "1/2", "1/2"), ("b", ("pb",), "1/2", "1/2"))
SOUTH_FREE = (("a", ("pa",), 0, 1), ("b", ("pb",), 0, 1))
NORTH_VARIABLE = (("a", ("feed", "pa"), "1/2", 1), ("b", ("pb",), 0, "1/2"))
SOUTH_VARIABLE = (("a", ("pa",), "1/4", "3/4"), ("b", ("pb",), "1/4", "3/4"))
NORTH_FOUR_WAYS = (
    ("a", ("feed", "pa"), 0, "1/2"),
    ("b", ("pb",), 0, "1/2"),
    ("closed", (), 0, "1/2"),
    ("full", ("feed", "pa", "pb"), 0, "1/2"),
)
EXAMPLES = (
    ("merged", NORTH_INTERVALS, SOUTH_POINT, "3/4", (Fraction(1, 2), Fraction(1)), "retest"),
    ("point", NORTH_POINT, SOUTH_POINT, "3/4", (Fraction(3, 4), Fraction(3, 4)), "pass"),
    ("shared", NORTH_HALF, SOUTH_FREE, "1/2", (Fraction(1, 2), Fraction(1, 2)), "pass"),
    ("two-bounds", NORTH_VARIABLE, SOUTH_VARIABLE, "1/2", (Fraction(1, 4), Fraction(3, 4)), "retest"),
    ("four-ways", NORTH_FOUR_WAYS, SOUTH_POINT, "1/2", (Fraction(0), Fraction(1)), "retest"),
)


def main() -> int:
    with closing(sqlite3.connect(":memory:")) as trials, closing(sqlite3.connect(":memory:")) as center:
        initialize_trials(trials)
        initialize_receipts(center)
        initialize_decisions(center)
        register(trials, ROUND, ROSTERS)
        with closing(sqlite3.connect(":memory:")) as source:
            initialize_revisions(source)
            initialize_issuance(source)
            north = ingest(trials, source, ROUND, "north", NORTH_PIPES, NORTH_NOMINAL)
            south = ingest(trials, source, ROUND, "south", SOUTH_PIPES, SOUTH_POINT)
            pieces = tuple(issue(trials, source, ROUND, row.station, row.revision_id)
                           for row in (north, south))
        ids = tuple(receive(trials, center, piece.payload) for piece in pieces)
        signed = sign(trials, center, ids, ENTRY, TARGETS, "3/4")
        decision, _ = signed
        if (decision.probability, decision.verdict) != (Fraction(3, 4), "pass"):
            print("V1 nominal comparison differs from 3/4 pass", file=sys.stderr)
            return 1
        if read(center, decision.report_id) != signed:
            print("V1 nominal report cannot be collected", file=sys.stderr)
            return 1
    print(f"V1 nominal: {decision.probability} {decision.verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
