import sys
import sqlite3
from contextlib import closing
from fractions import Fraction
from catalog import initialize_trials, register
from observations import LiveCircuit, PipeSegment, ingest, ingest_bounds, initialize_revisions
from receipt import initialize_receipts, receive
from report import initialize_decisions, read, sign, sign_bounds
from report.bounds import back_substitute
from receipt.intake import load_receipt
from station import initialize_issuance, issue
from station.decode import decode_any

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


def _issue_bounds_case(trials, source, center, name, north_circuits, south_circuits):
    north = ingest_bounds(trials, source, ROUND, "north", NORTH_PIPES, north_circuits)
    if south_circuits and isinstance(south_circuits[0], LiveCircuit):
        south = ingest(trials, source, ROUND, "south", SOUTH_PIPES, south_circuits)
    else:
        south = ingest_bounds(trials, source, ROUND, "south", SOUTH_PIPES, south_circuits)
    pieces = tuple(
        issue(trials, source, ROUND, revision.station, revision.revision_id)
        for revision in (north, south)
    )
    ids = tuple(receive(trials, center, piece.payload) for piece in pieces)
    return pieces, ids


def _check_witness_feasibility(pieces, decision):
    for index, piece in enumerate(pieces):
        decoded = decode_any(piece.payload)
        for witness in (decision.lower_witness, decision.upper_witness):
            masses = dict(witness[index])
            if sum(masses.values()) != 1:
                raise ValueError(f"witness masses for {piece.station} do not sum to one")
            for row in decoded.rows:
                mass = masses.get(row.blocks, Fraction(0))
                if hasattr(row, "lower"):
                    if not row.lower <= mass <= row.upper:
                        raise ValueError("witness mass leaves the partition interval")
                elif mass != row.mass:
                    raise ValueError("witness mass does not match the point-weight piece")


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

        with closing(sqlite3.connect(":memory:")) as source:
            initialize_revisions(source)
            initialize_issuance(source)
            for name, north_circuits, south_circuits, threshold, expected, expected_verdict in EXAMPLES:
                case_pieces, case_ids = _issue_bounds_case(
                    trials, source, center, name, north_circuits, south_circuits,
                )
                bounds_signed = sign_bounds(
                    trials, center, case_ids, ENTRY, TARGETS, threshold,
                )
                bounds_decision, bounds_receipt = bounds_signed
                actual = (bounds_decision.lower, bounds_decision.upper)
                if actual != expected or bounds_decision.verdict != expected_verdict:
                    print(
                        f"BOUNDS_MISMATCH {name} expected={expected} {expected_verdict} "
                        f"actual={actual} {bounds_decision.verdict}",
                        file=sys.stderr,
                    )
                    return 1
                pair = type(
                    "Pair", (),
                    {"first": load_receipt(center, case_ids[0]),
                     "second": load_receipt(center, case_ids[1])},
                )()
                if back_substitute(pair, bounds_decision.request,
                                   bounds_decision.lower_witness) != bounds_decision.lower:
                    print(f"BOUNDS_WITNESS_MISMATCH {name} lower", file=sys.stderr)
                    return 1
                if back_substitute(pair, bounds_decision.request,
                                   bounds_decision.upper_witness) != bounds_decision.upper:
                    print(f"BOUNDS_WITNESS_MISMATCH {name} upper", file=sys.stderr)
                    return 1
                _check_witness_feasibility(case_pieces, bounds_decision)
                if read(center, bounds_decision.report_id) != bounds_signed:
                    print(f"BOUNDS report {name} cannot be collected", file=sys.stderr)
                    return 1
                print(
                    f"bounds {name}: [{bounds_decision.lower}, {bounds_decision.upper}] "
                    f"{bounds_decision.verdict} (report {bounds_decision.report_id}, "
                    f"receipt {bounds_receipt.success_id})"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
