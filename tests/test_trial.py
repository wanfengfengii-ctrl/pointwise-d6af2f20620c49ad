import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from fractions import Fraction
from threading import Barrier

from catalog import initialize_trials, register
from demo import NORTH_PIPES, ROUND, ROSTERS, seed_sample
from observations import LiveCircuit, PipeSegment, ingest, initialize_revisions
from observations.revision_store import load_revision
from station import initialize_issuance, issue
from station.exchange import EvidenceRow, decode_piece
from tests import LabCase


class TrialTests(LabCase):
    def test_frozen_issue(self):
        north, south = seed_sample(self.trials, self.source)
        for revision in (north, south):
            with self.subTest(station=revision.station):
                first = self.freeze_revision(revision)
                self.assertEqual(self.freeze_revision(revision), first)
                piece = decode_piece(first.payload)
                self.assertEqual((piece.round_id, piece.station, piece.revision_id),
                                 (ROUND, revision.station, revision.revision_id))
                self.assertEqual(piece.issuance_id, first.issuance_id)
        self.assertEqual(self.source.execute('SELECT count(*) FROM issued_pieces').fetchone()[0], 2)

    def test_registration_conflict(self):
        trial = register(self.trials, ROUND, ROSTERS)
        self.assertEqual(register(self.trials, ROUND, {'south': ['B', 'A'], 'north': ['B', 'P', 'A']}), trial)
        with self.assertRaisesRegex(ValueError, 'conflicting roster'):
            register(self.trials, ROUND, {'north': ['P', 'A'], 'south': ['A', 'B']})
        for stations in ({'north': ['A']}, {'north': ['P', 'P'], 'south': ['A']},
                         {'north': 'P', 'south': ['A']}, {'north': list('ABCDE'), 'south': ['A']}):
            with self.subTest(stations=stations), self.assertRaises(ValueError):
                register(self.trials, 'bad-round', stations)
        self.assertEqual(self.trials.execute('SELECT count(*) FROM trials').fetchone()[0], 1)

    def test_private_bridge(self):
        register(self.trials, ROUND, {'north': ('P', 'X', 'Z'), 'south': ('X',)})
        revision = ingest(self.trials, self.source, ROUND, 'north', (
            PipeSegment('internal-1', 'P', 'hidden-vertex'),
            PipeSegment('internal-2', 'hidden-vertex', 'X'),
            PipeSegment('inactive', 'hidden-vertex', 'Z'),
        ), (LiveCircuit('raw-reading-17', ('internal-1', 'internal-2'), 1),))
        payload = self.freeze_revision(revision).payload
        self.assertEqual(decode_piece(payload).rows, (EvidenceRow((('P', 'X'), ('Z',)), Fraction(1)),))
        for private in ('hidden-vertex', 'internal-1', 'raw-reading-17', 'inactive'):
            self.assertNotIn(private, payload)

    def test_zero_weight_and_merged_partitions(self):
        register(self.trials, ROUND, {'north': ('P', 'A'), 'south': ()})
        revision = ingest(self.trials, self.source, ROUND, 'north', (PipeSegment('pa', 'P', 'A'),), (
            LiveCircuit('empty-one', (), '1/3'),
            LiveCircuit('empty-two', (), '2/3'),
            LiveCircuit('zero-connected', ('pa',), 0),
        ))
        self.assertEqual(revision.circuits[-1].mass, Fraction(0))
        self.assertIsInstance(revision.circuits[-1].mass, Fraction)
        piece = decode_piece(self.freeze_revision(revision).payload)
        self.assertEqual(piece.rows, (EvidenceRow((('A',), ('P',)), Fraction(1)),))

    def test_unknown_revision(self):
        north, _ = seed_sample(self.trials, self.source)
        for station, revision_id in (('north', 9999), ('south', north.revision_id)):
            with self.subTest(station=station), self.assertRaises(LookupError):
                issue(self.trials, self.source, ROUND, station, revision_id)
        self.assertEqual(self.source.execute('SELECT count(*) FROM issued_pieces').fetchone()[0], 0)

    def test_reject_invalid_weight(self):
        north, _ = seed_sample(self.trials, self.source)
        fixed = self.freeze_revision(north)
        for mass in ('3/4', '-1/4', '1/0', None, True, 1.0):
            with self.subTest(mass=mass), self.assertRaises(ValueError):
                ingest(self.trials, self.source, ROUND, 'north', NORTH_PIPES,
                       (LiveCircuit('bad', (), mass),), parent_id=north.revision_id)
        self.assertEqual(self.source.execute('SELECT count(*) FROM revisions').fetchone()[0], 2)
        self.assertEqual(self.freeze_revision(north), fixed)

    def test_reject_unknown_active_segment(self):
        north, _ = seed_sample(self.trials, self.source)
        with self.assertRaisesRegex(ValueError, 'unknown active segments'):
            ingest(self.trials, self.source, ROUND, 'north', NORTH_PIPES,
                   (LiveCircuit('bad', ('not-in-this-revision',), 1),), parent_id=north.revision_id)
        self.assertEqual(self.source.execute('SELECT count(*) FROM revisions').fetchone()[0], 2)

    def test_repeat_initialization(self):
        north, _ = seed_sample(self.trials, self.source)
        issued = self.freeze_revision(north)
        initialize_trials(self.trials)
        initialize_revisions(self.source)
        initialize_issuance(self.source)
        self.assertEqual(load_revision(self.source, ROUND, 'north', north.revision_id), north)
        self.assertEqual(self.freeze_revision(north), issued)

    def test_concurrent_first_issue(self):
        north, _ = seed_sample(self.trials, self.source)
        barrier = Barrier(2)

        def issue_from_separate_connection():
            with closing(sqlite3.connect(self.root / 'trials.sqlite3')) as trials:
                with closing(sqlite3.connect(self.root / 'source.sqlite3')) as source:
                    barrier.wait(timeout=5)
                    return issue(trials, source, ROUND, 'north', north.revision_id)

        with ThreadPoolExecutor(max_workers=2) as workers:
            requests = [workers.submit(issue_from_separate_connection) for _ in range(2)]
            first, second = (request.result() for request in requests)
        self.assertEqual(first, second)
        self.assertEqual(self.freeze_revision(north), first)
        self.assertEqual(self.source.execute('SELECT count(*) FROM issued_pieces').fetchone()[0], 1)
