import json
import sqlite3
import sys
from contextlib import closing
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from catalog import initialize_trials, register
from observations import LiveCircuit, PipeSegment, ingest, ingest_bounds, initialize_revisions
from receipt import initialize_receipts, receive
from report import initialize_decisions, read, sign, sign_bounds
from station import initialize_issuance, issue
from station.decode import decode_any

ROUND = 'bend-01'
ROSTERS = {'north': ('P', 'A', 'B'), 'south': ('A', 'B')}
NORTH_PIPES = (
    PipeSegment('feed', 'P', 'private-joint'),
    PipeSegment('branch-a', 'private-joint', 'A'),
    PipeSegment('branch-b', 'P', 'B'),
    PipeSegment('return', 'A', 'B'),
)
NORTH_INITIAL = (
    LiveCircuit('north-full', ('feed', 'branch-a', 'branch-b'), '1/2'),
    LiveCircuit('north-closed', (), '1/2'),
)
NORTH_CORRECTED = (
    LiveCircuit('north-corrected-full', ('feed', 'branch-a', 'branch-b'), '1/4'),
    LiveCircuit('north-corrected-a', ('feed', 'branch-a'), '1/4'),
    LiveCircuit('north-corrected-b', ('branch-b',), '1/4'),
    LiveCircuit('north-corrected-return', ('return',), '1/4'),
)
SOUTH_PIPES = (PipeSegment('link', 'A', 'B'),)
SOUTH_CIRCUITS = (LiveCircuit('south-open', ('link',), '1/4'), LiveCircuit('south-closed', (), '3/4'))

BOUNDS_ROUND = 'bounds-demo-01'
BOUNDS_ROSTERS = {'north': ('P', 'A', 'B'), 'south': ('P', 'A', 'B')}
BOUNDS_NORTH_PIPES = (
    PipeSegment('feed', 'P', 'north-private'),
    PipeSegment('pa', 'north-private', 'A'),
    PipeSegment('pb', 'P', 'B'),
)
BOUNDS_SOUTH_PIPES = (PipeSegment('pa', 'P', 'A'), PipeSegment('pb', 'P', 'B'))
BOUNDS_NORTH = (
    ('a-first', ('feed', 'pa'), '1/4', '1/2'),
    ('a-second', ('feed', 'pa'), '1/4', '1/2'),
    ('b', ('pb',), 0, '1/2'),
)
BOUNDS_SOUTH = (LiveCircuit('b', ('pb',), 1),)


def seed_sample(trials: sqlite3.Connection, source: sqlite3.Connection, round_id: str = ROUND):
    register(trials, round_id, ROSTERS)
    north = ingest(trials, source, round_id, 'north', NORTH_PIPES, NORTH_INITIAL)
    south = ingest(trials, source, round_id, 'south', SOUTH_PIPES, SOUTH_CIRCUITS)
    return north, south


def _expected_parents(pieces, receipt_ids):
    return [(receipt_id, piece.issuance_id, piece.station, piece.revision_id)
            for piece, receipt_id in zip(pieces, receipt_ids, strict=True)]


def _observed_parents(decision):
    return [(parent.receipt_id, parent.issuance_id, parent.station, parent.revision_id)
            for parent in decision.parents]


def run_bounds_demo(directory) -> int:
    """Issue interval pieces, take them offline, then sign and reopen by id."""
    root = Path(directory)
    source_path, center_path = root / 'bounds-source.sqlite3', root / 'bounds-center.sqlite3'
    with closing(sqlite3.connect(root / 'bounds-trials.sqlite3')) as trials:
        initialize_trials(trials)
        with closing(sqlite3.connect(source_path)) as source:
            initialize_revisions(source)
            initialize_issuance(source)
            register(trials, BOUNDS_ROUND, BOUNDS_ROSTERS)
            north = ingest_bounds(
                trials, source, BOUNDS_ROUND, 'north', BOUNDS_NORTH_PIPES, BOUNDS_NORTH,
            )
            south = ingest(
                trials, source, BOUNDS_ROUND, 'south', BOUNDS_SOUTH_PIPES, BOUNDS_SOUTH,
            )
            north_piece = issue(trials, source, BOUNDS_ROUND, 'north', north.revision_id)
            south_piece = issue(trials, source, BOUNDS_ROUND, 'south', south.revision_id)
            assert decode_any(north_piece.payload).issuance_id.startswith('v2-')

        # Source shut: the night shift only holds the roster and the offline pieces.
        with closing(sqlite3.connect(center_path)) as center:
            initialize_receipts(center)
            initialize_decisions(center)
            north_id = receive(trials, center, north_piece.payload)
            south_id = receive(trials, center, south_piece.payload)
            # Re-delivering the same piece returns the original receipt number.
            assert receive(trials, center, north_piece.payload) == north_id
            signed = sign_bounds(
                trials, center, (north_id, south_id), 'P', ('A', 'B'), '3/4',
            )

    with closing(sqlite3.connect(center_path)) as center:
        initialize_receipts(center)
        initialize_decisions(center)
        decision, receipt = read(center, signed[0].report_id)

    if (decision.lower, decision.upper, decision.verdict) != (
        Fraction(1, 2), Fraction(1), 'retest',
    ):
        print('BOUNDS_DECISION_MISMATCH', file=sys.stderr)
        return 1
    print(
        f'Bounds report {decision.report_id}: [{decision.lower}, {decision.upper}] '
        f'{decision.verdict} (success receipt {receipt.success_id}, station receipts '
        f'{decision.parents[0].receipt_id}/{decision.parents[1].receipt_id})'
    )
    print('BOUNDS_SCENARIO ' + json.dumps({
        'case_id': 'bounds-merged',
        'input': {
            'entry': 'P', 'targets': ['A', 'B'], 'threshold': '3/4',
            'north_intervals': {'a-first': ['1/4', '1/2'],
                                'a-second': ['1/4', '1/2'], 'b': ['0', '1/2']},
            'south_point': {'b': '1'},
        },
        'actual': {'lower': str(decision.lower), 'upper': str(decision.upper),
                   'verdict': decision.verdict},
        'lower_witness': [
            [[list(blocks), str(mass)] for blocks, mass in station]
            for station in decision.lower_witness
        ],
        'upper_witness': [
            [[list(blocks), str(mass)] for blocks, mass in station]
            for station in decision.upper_witness
        ],
    }, sort_keys=True))
    return 0


def main() -> int:
    with TemporaryDirectory(prefix='riverbend-') as directory:
        root = Path(directory)
        source_path, center_path = root / 'source.sqlite3', root / 'center.sqlite3'
        with closing(sqlite3.connect(root / 'trials.sqlite3')) as trials:
            initialize_trials(trials)
            with closing(sqlite3.connect(source_path)) as source:
                initialize_revisions(source)
                initialize_issuance(source)
                north, south = seed_sample(trials, source)
                north_piece = issue(trials, source, ROUND, 'north', north.revision_id)
                south_piece = issue(trials, source, ROUND, 'south', south.revision_id)

            with closing(sqlite3.connect(center_path)) as center:
                initialize_receipts(center)
                initialize_decisions(center)
                north_id = receive(trials, center, north_piece.payload)
                south_id = receive(trials, center, south_piece.payload)
                first = sign(trials, center, (north_id, south_id), 'P', ('A', 'B'), '1/2')

                with closing(sqlite3.connect(source_path)) as source:
                    initialize_revisions(source)
                    initialize_issuance(source)
                    corrected = ingest(
                        trials, source, ROUND, 'north', NORTH_PIPES, NORTH_CORRECTED,
                        parent_id=north.revision_id,
                    )
                    corrected_piece = issue(trials, source, ROUND, 'north', corrected.revision_id)

                corrected_id = receive(trials, center, corrected_piece.payload)
                revised = sign(trials, center, (corrected_id, south_id), 'P', ('A', 'B'), '1/2')

        with closing(sqlite3.connect(center_path)) as center:
            initialize_receipts(center)
            initialize_decisions(center)
            old_collected = read(center, first[0].report_id)
            new_collected = read(center, revised[0].report_id)

        expected = [(Fraction(1, 2), 'pass'), (Fraction(3, 8), 'retest')]
        actual = [(decision.probability, decision.verdict) for decision, _ in (first, revised)]
        if actual != expected:
            print(f'SUPPLY_DECISION_MISMATCH expected={expected} actual={actual}', file=sys.stderr)
            return 1

        expected_parents = [
            _expected_parents((north_piece, south_piece), (north_id, south_id)),
            _expected_parents((corrected_piece, south_piece), (corrected_id, south_id)),
        ]
        actual_parents = [_observed_parents(first[0]), _observed_parents(revised[0])]
        historical_match = old_collected == first and new_collected == revised
        if actual_parents != expected_parents or not historical_match:
            print('SUPPLY_HISTORY_MISMATCH', file=sys.stderr)
            return 1

        for decision, receipt in (old_collected, new_collected):
            print(f'Report {decision.report_id}: {decision.probability} {decision.verdict} '
                  f'(success receipt {receipt.success_id}, station receipts '
                  f'{decision.parents[0].receipt_id}/{decision.parents[1].receipt_id})')
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'v8',
            'input': {
                'entry': 'P', 'targets': ['A', 'B'], 'threshold': '1/2',
                'north_initial': {'all': '1/2', 'none': '1/2'},
                'north_corrected': {'all': '1/4', 'P-A': '1/4', 'P-B': '1/4', 'A-B': '1/4'},
                'south': {'A-B': '1/4', 'none': '3/4'},
            },
            'expected': [str(probability) for probability, _ in expected],
            'actual': [str(probability) for probability, _ in actual],
            'downstream_expected': {
                'verdicts': [verdict for _, verdict in expected],
                'parents': expected_parents, 'historical_match': True,
            },
            'downstream_actual': {
                'verdicts': [decision.verdict for decision, _ in (old_collected, new_collected)],
                'parents': actual_parents, 'historical_match': historical_match,
            },
            'code_paths': ['station/joint_law.py', 'receipt/intake.py', 'report/network.py',
                           'report/probability.py', 'report/decision_store.py', 'report/lookup.py'],
            'oracle': 'Initially only the all-connected northern state succeeds. After correction, '
                      'the all-connected state contributes 1/4 and the two one-branch states '
                      'contribute 1/16 each through the southern link.',
        }, sort_keys=True))
        if run_bounds_demo(directory):
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
