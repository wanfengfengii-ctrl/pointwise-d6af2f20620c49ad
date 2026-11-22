import sqlite3
from fractions import Fraction

from catalog import register
from demo import NORTH_CORRECTED, NORTH_PIPES, ROUND, seed_sample
from observations import LiveCircuit, PipeSegment, ingest
from report import read
from tests import LabCase


class DecisionTests(LabCase):
    def test_offline_equality(self):
        north, south = self.freeze_sample()
        self.source.close()
        north_id, south_id = self.receive_pieces(north, south)
        result, receipt = self.sign_pair((north_id, south_id))
        self.assertEqual(result.probability, Fraction(1, 2))
        self.assertIsInstance(result.probability, Fraction)
        self.assertEqual(result.verdict, 'pass')
        self.assertEqual((result.request.entry, result.request.targets, result.request.threshold),
                         ('P', ('A', 'B'), Fraction(1, 2)))
        self.assertEqual(tuple(parent.receipt_id for parent in result.parents), (north_id, south_id))
        self.assertEqual(tuple(parent.issuance_id for parent in result.parents), (north.issuance_id, south.issuance_id))
        self.assertEqual(read(self.center, result.report_id), (result, receipt))
        self.assertEqual(self.sign_counts(), (1, 1))

    def test_invalid_targets(self):
        receipts = self.offline_pair()
        for targets in (('A', 'A'), ('A', 'missing'), ('A',), 'AB', ('A', [])):
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                self.sign_pair(receipts, targets=targets)
        with self.assertRaises(ValueError):
            self.sign_pair(receipts, entry='missing')
        for threshold in ('1/0', '5/4', '-1/4', 0.5, True, None):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                self.sign_pair(receipts, threshold=threshold)
        self.assertEqual(self.sign_counts(), (0, 0))

    def _crossing_reports(self, first_pipes):
        register(self.trials, ROUND, {'north': ('P', 'X', 'Y', 'Z'), 'south': ('X', 'Y', 'Z', 'T')})
        north_pipes = (*first_pipes, PipeSegment('yz', 'Y', 'Z'))
        north = ingest(self.trials, self.source, ROUND, 'north', north_pipes,
                       (LiveCircuit('north-on', tuple(pipe.name for pipe in north_pipes), 1),))
        south_pipes = (PipeSegment('xy', 'X', 'Y'), PipeSegment('zt', 'Z', 'T'))
        south = ingest(self.trials, self.source, ROUND, 'south', south_pipes,
                       (LiveCircuit('south-on', ('xy', 'zt'), 1),))
        broken = ingest(self.trials, self.source, ROUND, 'south', south_pipes,
                        (LiveCircuit('south-open-end', ('xy',), 1),), parent_id=south.revision_id)
        pieces = tuple(self.freeze_revision(revision) for revision in (north, south, broken))
        self.source.close()
        north_id, south_id, broken_id = self.receive_pieces(*pieces)
        joined, joined_receipt = self.sign_pair((north_id, south_id), targets=('Z', 'T'))
        severed, severed_receipt = self.sign_pair((north_id, broken_id), targets=('Z', 'T'))
        self.assertEqual((joined.probability, joined.verdict), (Fraction(1), 'pass'))
        self.assertEqual((severed.probability, severed.verdict), (Fraction(0), 'retest'))
        self.assertEqual(read(self.center, joined.report_id), (joined, joined_receipt))
        self.assertEqual(read(self.center, severed.report_id), (severed, severed_receipt))

    def test_multiple_crossings(self):
        self._crossing_reports((PipeSegment('px', 'P', 'X'),))

    def test_private_bridge_crossings(self):
        self._crossing_reports((PipeSegment('pm', 'P', 'hidden'), PipeSegment('mx', 'hidden', 'X')))

    def test_empty_roster_and_entry_as_target(self):
        register(self.trials, ROUND, {'north': ('P', 'A'), 'south': ()})
        north = ingest(self.trials, self.source, ROUND, 'north', (PipeSegment('pa', 'P', 'A'),),
                       (LiveCircuit('on', ('pa',), 1),))
        south = ingest(self.trials, self.source, ROUND, 'south', (), (LiveCircuit('off', (), 1),))
        pieces = self.freeze_revision(north), self.freeze_revision(south)
        self.source.close()
        decision, _ = self.sign_pair(self.receive_pieces(*pieces), targets=('P', 'A'), threshold=1)
        self.assertEqual((decision.probability, decision.verdict), (Fraction(1), 'pass'))

    def test_wrong_round(self):
        north, _ = self.freeze_sample()
        _, other_south = self.freeze_sample('bend-02')
        self.source.close()
        pair = self.receive_pieces(north, other_south)
        with self.assertRaisesRegex(ValueError, 'different trial rounds'):
            self.sign_pair(pair)
        self.assertEqual(self.sign_counts(), (0, 0))

    def test_same_station(self):
        north, _ = seed_sample(self.trials, self.source)
        correction = ingest(self.trials, self.source, ROUND, 'north', NORTH_PIPES, NORTH_CORRECTED,
                            parent_id=north.revision_id)
        pieces = self.freeze_revision(north), self.freeze_revision(correction)
        self.source.close()
        first, second = self.receive_pieces(*pieces)
        for pair in ((first, second), (first, first)):
            with self.subTest(pair=pair), self.assertRaisesRegex(ValueError, 'different stations'):
                self.sign_pair(pair)
        with self.assertRaises(LookupError):
            self.sign_pair((first, 9999))
        self.assertEqual(self.sign_counts(), (0, 0))

    def test_failed_commit(self):
        pair = self.offline_pair()
        self.assertEqual(self.center.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        self.center.execute('CREATE TABLE allowed_commit (report_id INTEGER PRIMARY KEY)')
        self.center.execute('''
            CREATE TABLE deferred_commit (
                report_id INTEGER REFERENCES allowed_commit (report_id) DEFERRABLE INITIALLY DEFERRED
            )
        ''')
        self.center.execute('''
            CREATE TRIGGER fail_at_commit AFTER INSERT ON success_receipts
            BEGIN
                INSERT INTO deferred_commit (report_id) VALUES (NEW.report_id);
            END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
            self.sign_pair(pair)
        self.assertFalse(self.center.in_transaction)
        self.assertEqual(self.sign_counts(), (0, 0))
        self.assertEqual(self.center.execute('SELECT count(*) FROM deferred_commit').fetchone()[0], 0)
        self.reopen_center()
        self.assertEqual(self.sign_counts(), (0, 0))
        with self.assertRaises(LookupError):
            read(self.center, 1)

    def test_reopen_and_retry(self):
        pair = self.offline_pair()
        existing = self.sign_pair(pair)
        self.center.execute('''
            CREATE TRIGGER fail_receipt_write BEFORE INSERT ON success_receipts
            BEGIN
                SELECT RAISE(ABORT, 'receipt storage failed');
            END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'receipt storage failed'):
            self.sign_pair(pair)
        self.reopen_center()
        self.assertEqual(self.sign_counts(), (1, 1))
        old_report_id = existing[0].report_id
        self.assertEqual(read(self.center, old_report_id), existing)
        with self.assertRaises(LookupError):
            read(self.center, old_report_id + 1)
        self.center.execute('DROP TRIGGER fail_receipt_write')
        retried = self.sign_pair(pair)
        self.assertEqual(self.sign_counts(), (2, 2))
        self.assertEqual((retried[0].probability, retried[0].verdict), (Fraction(1, 2), 'pass'))
        self.assertEqual(read(self.center, retried[0].report_id), retried)
