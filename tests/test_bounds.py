import json
import random
import sqlite3
from contextlib import closing
from dataclasses import replace
from fractions import Fraction

import bounds_examples as bx
from catalog import register
from observations import (
    LiveCircuit,
    PipeSegment,
    ingest,
    ingest_bounds,
    initialize_revisions,
)
from observations.revision_store import load_any_revision, load_bounds_revision, load_revision
from receipt import initialize_receipts, receive
from receipt.intake import load_receipt
from report import initialize_decisions, read, sign, sign_bounds
from report.bounds import back_substitute, capped_simplex_vertices
from station import initialize_issuance, issue
from station.bounds_exchange import (
    BoundsStationPiece,
    bounds_issuance_identity,
    decode_bounds_piece,
    encode_bounds_piece,
)
from station.decode import decode_any
from station.exchange import StationPiece, decode_piece
from tests import LabCase


def _bounds_setup(case, name, north_circuits, south_circuits):
    register(case.trials, bx.ROUND, bx.ROSTERS)
    north = ingest_bounds(case.trials, case.source, bx.ROUND, 'north',
                          bx.NORTH_PIPES, north_circuits)
    if south_circuits and isinstance(south_circuits[0], LiveCircuit):
        south = ingest(case.trials, case.source, bx.ROUND, 'south',
                       bx.SOUTH_PIPES, south_circuits)
    else:
        south = ingest_bounds(case.trials, case.source, bx.ROUND, 'south',
                              bx.SOUTH_PIPES, south_circuits)
    north_piece = issue(case.trials, case.source, bx.ROUND, 'north', north.revision_id)
    south_piece = issue(case.trials, case.source, bx.ROUND, 'south', south.revision_id)
    ids = case.receive_pieces(north_piece, south_piece)
    return (north, south), (north_piece, south_piece), ids


class BoundsExampleTests(LabCase):
    def test_all_hand_computed_examples(self):
        for name, north_circuits, south_circuits, threshold, expected, expected_verdict in bx.EXAMPLES:
            with self.subTest(example=name):
                _revisions, pieces, ids = _bounds_setup(
                    self, name, north_circuits, south_circuits,
                )
                decision, receipt = sign_bounds(
                    self.trials, self.center, ids, bx.ENTRY, bx.TARGETS, threshold,
                )
                self.assertEqual((decision.lower, decision.upper), expected)
                self.assertEqual(decision.verdict, expected_verdict)
                pair = type('Pair', (), {
                    'first': load_receipt(self.center, ids[0]),
                    'second': load_receipt(self.center, ids[1]),
                })()
                self.assertEqual(
                    back_substitute(pair, decision.request, decision.lower_witness),
                    decision.lower,
                )
                self.assertEqual(
                    back_substitute(pair, decision.request, decision.upper_witness),
                    decision.upper,
                )
                for index, piece in enumerate(pieces):
                    decoded = decode_any(piece.payload)
                    for witness in (decision.lower_witness, decision.upper_witness):
                        masses = dict(witness[index])
                        self.assertEqual(sum(masses.values()), 1)
                        for row in decoded.rows:
                            mass = masses.get(row.blocks, Fraction(0))
                            if isinstance(decoded, BoundsStationPiece):
                                self.assertTrue(row.lower <= mass <= row.upper)
                            else:
                                self.assertEqual(mass, row.mass)
                self.assertEqual(read(self.center, decision.report_id), (decision, receipt))

    def test_threshold_equality_passes(self):
        _revisions, _pieces, ids = _bounds_setup(
            self, 'point', bx.NORTH_POINT, bx.SOUTH_POINT,
        )
        decision, _ = sign_bounds(
            self.trials, self.center, ids, bx.ENTRY, bx.TARGETS, Fraction(3, 4),
        )
        self.assertEqual(decision.lower, Fraction(3, 4))
        self.assertEqual(decision.verdict, 'pass')

    def test_witness_shape_and_lexicographic_order(self):
        _revisions, _pieces, ids = _bounds_setup(
            self, 'four-ways', bx.NORTH_FOUR_WAYS, bx.SOUTH_POINT,
        )
        decision, _ = sign_bounds(
            self.trials, self.center, ids, bx.ENTRY, bx.TARGETS, '1/2',
        )
        for witness in (decision.lower_witness, decision.upper_witness):
            self.assertEqual(len(witness), 2)
            for station in witness:
                blocks = tuple(item[0] for item in station)
                self.assertEqual(blocks, tuple(sorted(blocks)))
                for _blocks, mass in station:
                    self.assertIsInstance(mass, Fraction)
                    self.assertGreater(mass, 0)


class BoundsIngestTests(LabCase):
    def _round(self):
        register(self.trials, bx.ROUND, bx.ROSTERS)

    def test_reject_bad_intervals(self):
        self._round()
        cases = [
            (('a', ('feed',), '1/2', '1/4'),),
            (('a', ('feed',), -1, '1/2'),),
            (('a', ('feed',), 0, 2),),
            (('a', ('feed',), 0.5, 1),),
            (('a', ('feed',), True, 1),),
            (('a', ('feed',), None, 1),),
            (('a', ('feed',), '1/0', 1),),
            (('a', ('feed',), 1, 1), ('b', (), '1/4', '1/2')),
            (('a', ('missing',), 0, 1),),
        ]
        for circuits in cases:
            with self.subTest(circuits=circuits):
                with self.assertRaises(ValueError):
                    ingest_bounds(self.trials, self.source, bx.ROUND, 'north',
                                  bx.NORTH_PIPES, circuits)
        self.assertEqual(self.source.execute('SELECT count(*) FROM revisions').fetchone()[0], 0)

    def test_duplicate_observation_and_segment_rules(self):
        self._round()
        with self.assertRaises(ValueError):
            ingest_bounds(self.trials, self.source, bx.ROUND, 'north', bx.NORTH_PIPES, (
                ('dup', (), 0, '1/2'), ('dup', (), '1/2', 1),
            ))
        with self.assertRaises(ValueError):
            ingest_bounds(self.trials, self.source, bx.ROUND, 'north', (
                PipeSegment('dup', 'P', 'A'), PipeSegment('dup', 'P', 'B'),
            ), (('a', ('dup',), 0, 1),))

    def test_equal_endpoints_zero_weights_and_caller_isolation(self):
        self._round()
        active = ['feed', 'pa']
        revision = ingest_bounds(self.trials, self.source, bx.ROUND, 'north', bx.NORTH_PIPES, (
            ('point-circuit', active, '3/8', '3/8'),
            ('zero-circuit', (), 0, 0),
            ('rest', (), '5/8', '5/8'),
        ))
        active.append('pb')
        self.assertEqual(revision.circuits[0].active, ('feed', 'pa'))
        self.assertEqual(revision.circuits[0].lower, Fraction(3, 8))
        self.assertEqual(revision.circuits[0].upper, Fraction(3, 8))
        self.assertEqual(revision.circuits[1].upper, Fraction(0))
        stored = load_bounds_revision(self.source, bx.ROUND, 'north', revision.revision_id)
        self.assertEqual(stored, revision)
        with self.assertRaises(LookupError):
            load_revision(self.source, bx.ROUND, 'north', revision.revision_id)

    def test_parent_may_be_either_kind_and_scoped(self):
        self._round()
        point = ingest(self.trials, self.source, bx.ROUND, 'north',
                       bx.NORTH_PIPES, bx.NORTH_NOMINAL)
        child = ingest_bounds(
            self.trials, self.source, bx.ROUND, 'north', bx.NORTH_PIPES,
            bx.NORTH_INTERVALS, parent_id=point.revision_id,
        )
        self.assertEqual(child.parent_id, point.revision_id)
        grandchild = ingest_bounds(
            self.trials, self.source, bx.ROUND, 'north', bx.NORTH_PIPES,
            bx.NORTH_HALF, parent_id=child.revision_id,
        )
        self.assertEqual(load_any_revision(
            self.source, bx.ROUND, 'north', point.revision_id).revision_id, point.revision_id)
        other = ingest(self.trials, self.source, bx.ROUND, 'south',
                       bx.SOUTH_PIPES, bx.SOUTH_POINT)
        for bad_parent in (other.revision_id, 9999):
            with self.subTest(parent=bad_parent):
                with self.assertRaises(LookupError):
                    ingest_bounds(self.trials, self.source, bx.ROUND, 'north',
                                  bx.NORTH_PIPES, bx.NORTH_HALF, parent_id=bad_parent)
        self.assertEqual(grandchild.parent_id, child.revision_id)


class BoundsPieceTests(LabCase):
    def test_v2_encoding_keeps_private_details_inside_source(self):
        register(self.trials, bx.ROUND, bx.ROSTERS)
        revision = ingest_bounds(self.trials, self.source, bx.ROUND, 'north',
                                 bx.NORTH_PIPES, bx.NORTH_INTERVALS)
        piece = issue(self.trials, self.source, bx.ROUND, 'north', revision.revision_id)
        self.assertTrue(piece.issuance_id.startswith('v2-'))
        self.assertEqual(
            piece.issuance_id,
            bounds_issuance_identity(bx.ROUND, 'north', revision.revision_id),
        )
        decoded = decode_bounds_piece(piece.payload)
        self.assertIsInstance(decoded, BoundsStationPiece)
        envelope = json.loads(piece.payload)
        self.assertEqual(envelope['version'], 2)
        for field in ('version', 'issuance_id', 'round_id', 'station', 'revision_id', 'ports', 'rows'):
            self.assertIn(field, envelope)
        for secret in ('a-first', 'a-second', 'feed', 'pa', 'pb', 'north-private'):
            self.assertNotIn(secret, piece.payload)
        # Only the two distinct public partitions survive, with merged intervals.
        rows = {row.blocks: (row.lower, row.upper) for row in decoded.rows}
        self.assertEqual(rows, {
            (('A', 'P'), ('B',)): (Fraction(1, 2), Fraction(1)),
            (('A',), ('B', 'P')): (Fraction(0), Fraction(1, 2)),
        })
        # Re-issue returns the exact same piece.
        self.assertEqual(
            issue(self.trials, self.source, bx.ROUND, 'north', revision.revision_id),
            piece,
        )
        # A point revision keeps its v1 identity and encoding.
        point = ingest(self.trials, self.source, bx.ROUND, 'south',
                       bx.SOUTH_PIPES, bx.SOUTH_POINT)
        point_piece = issue(self.trials, self.source, bx.ROUND, 'south', point.revision_id)
        self.assertTrue(point_piece.issuance_id.startswith('v1-'))
        self.assertIsInstance(decode_piece(point_piece.payload), StationPiece)
        self.assertIsInstance(decode_any(point_piece.payload), StationPiece)
        self.assertIsInstance(decode_any(piece.payload), BoundsStationPiece)

    def test_zero_upper_partitions_are_omitted(self):
        register(self.trials, bx.ROUND, bx.ROSTERS)
        revision = ingest_bounds(self.trials, self.source, bx.ROUND, 'north',
                                 bx.NORTH_PIPES, (
            ('a', ('feed', 'pa'), '1/2', '1/2'),
            ('closed', (), 0, 0),
            ('b', ('pb',), '1/2', '1/2'),
        ))
        decoded = decode_bounds_piece(
            issue(self.trials, self.source, bx.ROUND, 'north', revision.revision_id).payload,
        )
        self.assertEqual({row.blocks for row in decoded.rows}, {
            (('A', 'P'), ('B',)), (('A',), ('B', 'P')),
        })

    def test_aggregated_intervals_cover_exactly_the_realizable_partition_masses(self):
        register(self.trials, 'r2', {'north': ('P', 'A'), 'south': ()})
        revision = ingest_bounds(self.trials, self.source, 'r2', 'north',
                                 (PipeSegment('pa', 'P', 'A'),), (
            ('c1', ('pa',), '1/4', '1/2'),
            ('c2', ('pa',), '1/4', '1/2'),
            ('c3', (), 0, '1/2'),
        ))
        decoded = decode_bounds_piece(
            issue(self.trials, self.source, 'r2', 'north', revision.revision_id).payload,
        )
        rows = {row.blocks: (row.lower, row.upper) for row in decoded.rows}
        # The two A-circuits merge into the connected partition as [1/2, 1].
        self.assertEqual(rows[(('A', 'P'),)], (Fraction(1, 2), Fraction(1)))
        self.assertEqual(rows[(('A',), ('P',))], (Fraction(0), Fraction(1, 2)))
        # Every polytope vertex must be decomposable back into original-circuit
        # allocations: the connected mass always lies between 1/2 and 1.
        by_blocks = {row.blocks: index for index, row in enumerate(decoded.rows)}
        connected_index = by_blocks[(('A', 'P'),)]
        isolated_index = by_blocks[(('A',), ('P',))]
        lows = tuple(row.lower for row in decoded.rows)
        highs = tuple(row.upper for row in decoded.rows)
        for point in capped_simplex_vertices(lows, highs):
            connected, isolated = point[connected_index], point[isolated_index]
            self.assertTrue(Fraction(1, 2) <= connected <= 1)
            self.assertTrue(0 <= isolated <= Fraction(1, 2))
            self.assertEqual(connected + isolated, 1)

    def test_empty_roster_piece_uses_the_empty_partition(self):
        register(self.trials, 'r3', {'north': ('P', 'A', 'B'), 'south': ()})
        north = ingest_bounds(self.trials, self.source, 'r3', 'north',
                              bx.NORTH_PIPES, bx.NORTH_INTERVALS)
        south = ingest_bounds(self.trials, self.source, 'r3', 'south', (),
                              (('off', (), 1, 1),))
        north_piece = issue(self.trials, self.source, 'r3', 'north', north.revision_id)
        south_piece = issue(self.trials, self.source, 'r3', 'south', south.revision_id)
        south_decoded = decode_bounds_piece(south_piece.payload)
        self.assertEqual(south_decoded.rows[0].blocks, ())
        self.assertEqual((south_decoded.rows[0].lower, south_decoded.rows[0].upper),
                         (Fraction(1), Fraction(1)))
        ids = self.receive_pieces(north_piece, south_piece)
        decision, _ = sign_bounds(
            self.trials, self.center, ids, 'P', ('A', 'B'), '1/2',
        )
        # With no southern public junction, both targets cannot be joined.
        self.assertEqual((decision.lower, decision.upper), (Fraction(0), Fraction(0)))
        self.assertEqual(decision.verdict, 'retest')


class BoundsReceiptTests(LabCase):
    def _pieces(self):
        register(self.trials, bx.ROUND, bx.ROSTERS)
        north = ingest_bounds(self.trials, self.source, bx.ROUND, 'north',
                              bx.NORTH_PIPES, bx.NORTH_INTERVALS)
        south = ingest_bounds(self.trials, self.source, bx.ROUND, 'south',
                              bx.SOUTH_PIPES, bx.SOUTH_FREE)
        north_piece = issue(self.trials, self.source, bx.ROUND, 'north', north.revision_id)
        south_piece = issue(self.trials, self.source, bx.ROUND, 'south', south.revision_id)
        self.source.close()
        return north_piece, south_piece

    def test_replay_keeps_receipt_number(self):
        north, south = self._pieces()
        first = receive(self.trials, self.center, north.payload)
        reordered = json.dumps(json.loads(north.payload), indent=2)
        self.assertEqual(receive(self.trials, self.center, reordered), first)
        self.assertEqual(receive(self.trials, self.center, north.payload), first)
        self.assertEqual(
            load_receipt(self.center, first).piece.issuance_id, north.issuance_id,
        )
        self.assertEqual(self.center.execute(
            'SELECT count(*) FROM received_pieces').fetchone()[0], 1)

    def test_malformed_and_infeasible_pieces_rejected_with_old_books_intact(self):
        north, _south = self._pieces()
        raw = json.loads(north.payload)
        variants = []
        edited = json.loads(north.payload)
        edited['version'] = 1
        variants.append(json.dumps(edited))
        edited = json.loads(north.payload)
        edited['rows'][0]['upper'] = [1, 0]
        variants.append(json.dumps(edited))
        edited = json.loads(north.payload)
        edited['rows'][0]['lower'], edited['rows'][0]['upper'] = (
            edited['rows'][0]['upper'], edited['rows'][0]['lower'])
        variants.append(json.dumps(edited))
        edited = json.loads(north.payload)
        edited['rows'][0]['lower'] = [2, 1]
        variants.append(json.dumps(edited))
        edited = json.loads(north.payload)
        edited['issuance_id'] = 'v2-deadbeef'
        variants.append(json.dumps(edited))
        edited = json.loads(north.payload)
        edited['ports'] = ['A', 'B']
        variants.append(json.dumps(edited))
        for payload in variants:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    receive(self.trials, self.center, payload)
        self.assertEqual(self.center.execute(
            'SELECT count(*) FROM received_pieces').fetchone()[0], 0)
        # Infeasible intervals: rows sum to a lower total above one.
        decoded = decode_bounds_piece(north.payload)
        infeasible = replace(decoded, rows=tuple(
            replace(row, lower=Fraction(3, 4)) for row in decoded.rows
        ))
        with self.assertRaises(ValueError):
            receive(self.trials, self.center, encode_bounds_piece(infeasible))
        # Structural defect: partition missing a port.
        broken = replace(decoded, rows=(replace(decoded.rows[0], blocks=(('A', 'P'),)),))
        with self.assertRaises(ValueError):
            receive(self.trials, self.center, encode_bounds_piece(broken))
        self.assertEqual(self.center.execute(
            'SELECT count(*) FROM received_pieces').fetchone()[0], 0)

    def test_conflicting_body_rejected_but_replay_remains(self):
        north, south = self._pieces()
        north_id, south_id = self.receive_pieces(north, south)
        decoded = decode_bounds_piece(north.payload)
        conflict = replace(decoded, rows=(
            replace(decoded.rows[0], upper=Fraction(1)), *decoded.rows[1:],
        ))
        with self.assertRaisesRegex(ValueError, 'conflicting content'):
            receive(self.trials, self.center, encode_bounds_piece(conflict))
        self.assertEqual(receive(self.trials, self.center, north.payload), north_id)
        self.assertEqual(self.center.execute(
            'SELECT count(*) FROM received_pieces').fetchone()[0], 2)


class BoundsSignoffTests(LabCase):
    def _pair(self, north_circuits=bx.NORTH_INTERVALS, south_circuits=bx.SOUTH_FREE):
        return _bounds_setup(self, 'case', north_circuits, south_circuits)[2]

    def test_point_sign_rejects_bounds_pieces(self):
        ids = self._pair()
        with self.assertRaisesRegex(ValueError, 'sign_bounds'):
            sign(self.trials, self.center, ids, 'P', ('A', 'B'), '1/2')
        self.assertEqual(self.center.execute('SELECT count(*) FROM decisions').fetchone()[0], 0)

    def test_mixed_point_and_bounds_pieces(self):
        ids = self._pair(bx.NORTH_INTERVALS, bx.SOUTH_POINT)
        decision, _ = sign_bounds(
            self.trials, self.center, ids, 'P', ('A', 'B'), '3/4',
        )
        self.assertEqual((decision.lower, decision.upper), (Fraction(1, 2), Fraction(1)))
        self.assertEqual(decision.verdict, 'retest')
        first_piece = load_receipt(self.center, ids[0]).piece
        second_piece = load_receipt(self.center, ids[1]).piece
        self.assertIsInstance(first_piece, BoundsStationPiece)
        self.assertIsInstance(second_piece, StationPiece)

    def test_parent_order_and_round_station_rules(self):
        ids = self._pair()
        decision, _ = sign_bounds(
            self.trials, self.center, (ids[1], ids[0]), 'P', ('A', 'B'), '1/2',
        )
        self.assertEqual(tuple(parent.station for parent in decision.parents),
                         ('south', 'north'))
        with self.assertRaises(ValueError):
            sign_bounds(self.trials, self.center, (ids[0], ids[0]),
                        'P', ('A', 'B'), '1/2')
        with self.assertRaises(LookupError):
            sign_bounds(self.trials, self.center, (ids[0], 9999),
                        'P', ('A', 'B'), '1/2')

    def test_failed_commit_rolls_back_report_and_receipt(self):
        ids = self._pair()
        self.center.execute('CREATE TABLE allowed_commit (report_id INTEGER PRIMARY KEY)')
        self.center.execute('''
            CREATE TABLE deferred_commit (
                report_id INTEGER REFERENCES allowed_commit (report_id)
                DEFERRABLE INITIALLY DEFERRED
            )
        ''')
        self.center.execute('''
            CREATE TRIGGER fail_bounds_commit AFTER INSERT ON success_receipts
            BEGIN
                INSERT INTO deferred_commit (report_id) VALUES (NEW.report_id);
            END
        ''')
        with self.assertRaises(sqlite3.IntegrityError):
            sign_bounds(self.trials, self.center, ids, 'P', ('A', 'B'), '1/2')
        self.assertFalse(self.center.in_transaction)
        self.assertEqual(self.center.execute('SELECT count(*) FROM decisions').fetchone()[0], 0)
        self.assertEqual(self.center.execute(
            'SELECT count(*) FROM success_receipts').fetchone()[0], 0)
        self.reopen_center()
        with self.assertRaises(LookupError):
            read(self.center, 1)

    def test_reopen_center_keeps_finalized_bounds_report(self):
        ids = self._pair()
        signed = sign_bounds(
            self.trials, self.center, ids, 'P', ('A', 'B'), '1/2',
        )
        report_id = signed[0].report_id
        self.reopen_center()
        self.assertEqual(read(self.center, report_id), signed)
        # Re-signing creates a fresh report while the original stays intact.
        again = sign_bounds(
            self.trials, self.center, ids, 'P', ('A', 'B'), '1/2',
        )
        self.assertNotEqual(again[0].report_id, report_id)
        self.assertEqual(read(self.center, report_id), signed)
        with self.assertRaises(LookupError):
            read(self.center, report_id + 100)

    def test_source_offline_collection_needs_only_center(self):
        _revisions, pieces, ids = _bounds_setup(
            self, 'merged', bx.NORTH_INTERVALS, bx.SOUTH_POINT,
        )
        signed = sign_bounds(
            self.trials, self.center, ids, 'P', ('A', 'B'), '3/4',
        )
        self.source.close()
        self.trials.close()
        self.reopen_center()
        self.assertEqual(read(self.center, signed[0].report_id), signed)


class VertexTests(LabCase):
    def test_simplex_vertices_are_unit_vectors(self):
        for size in range(1, 10):
            vertices = capped_simplex_vertices(
                tuple(Fraction(0) for _ in range(size)),
                tuple(Fraction(1) for _ in range(size)),
            )
            self.assertEqual(len(vertices), size)
            for point in vertices:
                self.assertEqual(sum(point), 1)

    def test_point_polytope_and_infeasibility(self):
        point = capped_simplex_vertices((Fraction(1, 3), Fraction(2, 3)),
                                        (Fraction(1, 3), Fraction(2, 3)))
        self.assertEqual(point, ((Fraction(1, 3), Fraction(2, 3)),))
        with self.assertRaises(ValueError):
            capped_simplex_vertices((Fraction(0),) * 3, (Fraction(1, 4),) * 3)
        with self.assertRaises(ValueError):
            capped_simplex_vertices((Fraction(3, 4), Fraction(3, 4)),
                                    (Fraction(1), Fraction(1)))

    def test_capped_vertices_stay_inside_box(self):
        lower = tuple(Fraction(1, 30) for _ in range(10))
        upper = tuple(Fraction(1, 5) for _ in range(10))
        vertices = capped_simplex_vertices(lower, upper)
        for point in vertices:
            self.assertEqual(sum(point), 1)
            for index, value in enumerate(point):
                self.assertTrue(lower[index] <= value <= upper[index])

    def test_integer_greedy_matches_exhaustive_bilinear_extrema(self):
        from report.bounds import (
            _scale,
            integer_capped_simplex_vertices,
            integer_greedy_extreme,
        )
        rng = random.Random(2026)

        def make_bounds(size):
            while True:
                low = [Fraction(rng.randint(0, 2), rng.randint(3, 6)) for _ in range(size)]
                high = [
                    min(value + Fraction(rng.randint(0, 3), rng.randint(4, 8)), 1)
                    for value in low
                ]
                if sum(low) <= 1 <= sum(high) and all(a <= b for a, b in zip(low, high)):
                    return tuple(low), tuple(high)

        for _ in range(120):
            n, m = rng.randint(1, 5), rng.randint(1, 5)
            first_low, first_high = make_bounds(n)
            second_low, second_high = make_bounds(m)
            reach = tuple(tuple(rng.randint(0, 1) for _ in range(m)) for _ in range(n))
            exhaustive = [
                sum(
                    reach[i][j] * first[i] * second[j]
                    for i in range(n) for j in range(m)
                )
                for first in capped_simplex_vertices(first_low, first_high)
                for second in capped_simplex_vertices(second_low, second_high)
            ]
            d1, il1, ih1 = _scale(first_low, first_high)
            d2, il2, ih2 = _scale(second_low, second_high)
            integer_low = integer_high = None
            for first in integer_capped_simplex_vertices(il1, ih1, d1):
                coefficients = tuple(
                    sum(reach[i][j] * first[i] for i in range(n)) for j in range(m)
                )
                for maximize in (False, True):
                    second = integer_greedy_extreme(
                        coefficients, il2, ih2, d2, maximize,
                    )
                    numerator = sum(
                        reach[i][j] * first[i] * second[j]
                        for i in range(n) for j in range(m)
                    )
                    integer_low = numerator if integer_low is None \
                        else min(integer_low, numerator)
                    integer_high = numerator if integer_high is None \
                        else max(integer_high, numerator)
            self.assertEqual(Fraction(integer_low, d1 * d2), min(exhaustive))
            self.assertEqual(Fraction(integer_high, d1 * d2), max(exhaustive))

    def test_large_polytope_stays_tractable(self):
        from report.bounds import integer_capped_simplex_vertices, _scale
        lower = tuple(Fraction(1, 30) for _ in range(15))
        upper = tuple(Fraction(1, 10) for _ in range(15))
        denominator, low, high = _scale(lower, upper)
        vertices = integer_capped_simplex_vertices(low, high, denominator)
        self.assertGreater(len(vertices), 1000)
        for point in vertices:
            self.assertEqual(sum(point), denominator)
            for index, value in enumerate(point):
                self.assertTrue(low[index] <= value <= high[index])


class LegacyMigrationTests(LabCase):
    def test_v1_center_schema_upgrades_and_keeps_finalized_reports(self):
        self.center.close()
        path = self.root / 'center.sqlite3'
        path.unlink()
        with closing(sqlite3.connect(path)) as legacy:
            legacy.execute('''
                CREATE TABLE decisions (
                    report_id INTEGER PRIMARY KEY,
                    request_snapshot TEXT NOT NULL,
                    ordered_parents TEXT NOT NULL,
                    probability TEXT NOT NULL,
                    verdict TEXT NOT NULL CHECK (verdict IN ('pass', 'retest'))
                )
            ''')
            legacy.execute('''
                CREATE TABLE success_receipts (
                    success_id INTEGER PRIMARY KEY,
                    report_id INTEGER NOT NULL UNIQUE REFERENCES decisions (report_id)
                )
            ''')
            legacy.execute(
                "INSERT INTO decisions VALUES (1, ?, '[]', '1/2', 'pass')",
                (json.dumps(['bend-01', 'P', ['A', 'B'], '1/2']),),
            )
            legacy.execute('INSERT INTO success_receipts VALUES (7, 1)')
            legacy.commit()
        self.center = self.open_book('center', initialize_receipts, initialize_decisions)
        self.assertEqual(self.center.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        decision, receipt = read(self.center, 1)
        self.assertEqual(decision.probability, Fraction(1, 2))
        self.assertEqual(decision.verdict, 'pass')
        self.assertEqual((receipt.success_id, receipt.report_id), (7, 1))
        # Initialization is idempotent and the legacy report remains readable.
        initialize_decisions(self.center)
        self.assertEqual(read(self.center, 1)[0].probability, Fraction(1, 2))

    def test_v1_revision_schema_upgrades(self):
        self.source.close()
        path = self.root / 'source.sqlite3'
        path.unlink()
        with closing(sqlite3.connect(path)) as legacy:
            legacy.execute('''
                CREATE TABLE revisions (
                    revision_id INTEGER PRIMARY KEY,
                    round_id TEXT NOT NULL,
                    station TEXT NOT NULL,
                    parent_id INTEGER,
                    original_observations TEXT NOT NULL,
                    UNIQUE (round_id, station, revision_id)
                )
            ''')
            payload = json.dumps({'segments': [], 'circuits': [('c', [], [1, 1])]})
            legacy.execute(
                "INSERT INTO revisions VALUES (1, 'bend-01', 'north', NULL, ?)", (payload,),
            )
            legacy.commit()
        self.source = self.open_book('source', initialize_revisions, initialize_issuance)
        revision = load_revision(self.source, 'bend-01', 'north', 1)
        self.assertEqual(revision.circuits[0].mass, Fraction(1))
        initialize_revisions(self.source)
        self.assertEqual(
            load_any_revision(self.source, 'bend-01', 'north', 1).revision_id, 1,
        )
