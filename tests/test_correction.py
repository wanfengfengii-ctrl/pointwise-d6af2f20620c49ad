import sqlite3
from fractions import Fraction
from itertools import combinations

from catalog import initialize_trials
from demo import NORTH_CORRECTED, NORTH_INITIAL, NORTH_PIPES, ROUND, seed_sample
from observations import LiveCircuit, ingest, initialize_revisions
from observations.revision_store import load_revision
from receipt.intake import load_receipt
from report import read
from station import initialize_issuance
from station.exchange import EvidenceRow, decode_piece
from tests import LabCase


class CorrectionTests(LabCase):
    def _versions(self):
        north, south = seed_sample(self.trials, self.source)
        north_piece = self.freeze_revision(north)
        south_piece = self.freeze_revision(south)
        corrected = ingest(self.trials, self.source, ROUND, 'north', NORTH_PIPES, NORTH_CORRECTED,
                            parent_id=north.revision_id)
        corrected_piece = self.freeze_revision(corrected)
        return (north, corrected, south), (north_piece, corrected_piece, south_piece)

    def _assert_parent_bindings(self, decision, ids, pieces):
        self.assertEqual(decision.request.round_id, ROUND)
        self.assertEqual(tuple(parent.receipt_id for parent in decision.parents), ids)
        self.assertEqual(tuple(parent.issuance_id for parent in decision.parents),
                         tuple(piece.issuance_id for piece in pieces))
        self.assertEqual(tuple(parent.revision_id for parent in decision.parents),
                         tuple(piece.revision_id for piece in pieces))
        self.assertEqual(tuple(parent.station for parent in decision.parents),
                         tuple(piece.station for piece in pieces))

    def test_identical_marginals_after_correction(self):
        north, south = seed_sample(self.trials, self.source)
        north_piece, south_piece = self.freeze_revision(north), self.freeze_revision(south)
        self.source.close()
        north_id, south_id = self.receive_pieces(north_piece, south_piece)
        first = self.sign_pair((north_id, south_id))
        self.assertEqual((first[0].probability, first[0].verdict), (Fraction(1, 2), 'pass'))

        self.source = self.open_book('source', initialize_revisions, initialize_issuance)
        corrected = ingest(self.trials, self.source, ROUND, 'north', NORTH_PIPES, NORTH_CORRECTED,
                            parent_id=north.revision_id)
        corrected_piece = self.freeze_revision(corrected)
        self.source.close()
        corrected_id, = self.receive_pieces(corrected_piece)
        latest = self.sign_pair((corrected_id, south_id))
        self.assertEqual((latest[0].probability, latest[0].verdict), (Fraction(3, 8), 'retest'))
        self._assert_parent_bindings(first[0], (north_id, south_id), (north_piece, south_piece))
        self._assert_parent_bindings(latest[0], (corrected_id, south_id), (corrected_piece, south_piece))
        self.assertNotEqual(first[0].report_id, latest[0].report_id)
        self.assertEqual(first[1].report_id, first[0].report_id)
        self.assertEqual(latest[1].report_id, latest[0].report_id)
        self.reopen_center()
        self.assertEqual(read(self.center, first[0].report_id), first)
        self.assertEqual(read(self.center, latest[0].report_id), latest)
        self.assertEqual(self.sign_counts(), (2, 2))

    def test_distinct_joint_laws(self):
        _, (first, corrected, _) = self._versions()
        initial, revised = decode_piece(first.payload), decode_piece(corrected.payload)
        self.assertEqual({row.blocks: row.mass for row in initial.rows}, {
            (('A',), ('B',), ('P',)): Fraction(1, 2),
            (('A', 'B', 'P'),): Fraction(1, 2),
        })
        self.assertEqual({row.blocks: row.mass for row in revised.rows}, {
            (('A', 'B', 'P'),): Fraction(1, 4),
            (('A', 'P'), ('B',)): Fraction(1, 4),
            (('A',), ('B', 'P')): Fraction(1, 4),
            (('A', 'B'), ('P',)): Fraction(1, 4),
        })
        for left, right in combinations(('A', 'B', 'P'), 2):
            for piece in (initial, revised):
                mass = sum(row.mass for row in piece.rows
                           if any(left in block and right in block for block in row.blocks))
                self.assertEqual(mass, Fraction(1, 2))
        self.assertEqual(decode_piece(self.freeze_revision(load_revision(
            self.source, ROUND, 'north', revised.revision_id)).payload).rows, revised.rows)

    def test_parent_scope(self):
        north, south = seed_sample(self.trials, self.source)
        other_north, _ = seed_sample(self.trials, self.source, 'bend-02')
        for parent_id in (south.revision_id, other_north.revision_id, 9999):
            with self.subTest(parent=parent_id), self.assertRaises(LookupError):
                ingest(self.trials, self.source, ROUND, 'north', NORTH_PIPES, NORTH_CORRECTED,
                       parent_id=parent_id)
        self.assertEqual(self.source.execute('SELECT count(*) FROM revisions').fetchone()[0], 4)
        self.assertEqual(load_revision(self.source, ROUND, 'north', north.revision_id), north)

    def test_immutable_revisions(self):
        north, _ = seed_sample(self.trials, self.source)
        active = ['feed', 'branch-a']
        pipes = list(NORTH_PIPES)
        recorded = ingest(self.trials, self.source, ROUND, 'north', pipes,
                          (LiveCircuit('replacement', active, '1'),), parent_id=north.revision_id)
        active.clear()
        pipes.clear()
        self.assertEqual(recorded.circuits[0].active, ('branch-a', 'feed'))
        self.assertEqual(recorded.circuits[0].mass, Fraction(1))
        self.assertEqual(recorded.parent_id, north.revision_id)
        self.assertEqual(load_revision(self.source, ROUND, 'north', recorded.revision_id), recorded)
        original = load_revision(self.source, ROUND, 'north', north.revision_id)
        self.assertEqual(original, north)
        self.assertEqual(original.circuits[0].observation_id, NORTH_INITIAL[0].observation_id)
        self.assertEqual(original.circuits[0].mass, Fraction(1, 2))
        rows = decode_piece(self.freeze_revision(recorded).payload).rows
        self.assertEqual(rows, (EvidenceRow((('A', 'P'), ('B',)), Fraction(1)),))

    def test_exact_reissue(self):
        (north, corrected, _), (first, revised, _) = self._versions()
        self.source.close()
        self.source = self.open_book('source', initialize_revisions, initialize_issuance)
        self.assertEqual(self.freeze_revision(north), first)
        self.assertEqual(self.freeze_revision(corrected), revised)
        self.assertNotEqual(first.issuance_id, revised.issuance_id)

    def test_pinned_receipts(self):
        _, (first, corrected, south) = self._versions()
        self.source.close()
        corrected_id, south_id, original_id = self.receive_pieces(corrected, south, first)
        old, _ = self.sign_pair((south_id, original_id))
        new, _ = self.sign_pair((corrected_id, south_id))
        self.assertEqual((old.probability, new.probability), (Fraction(1, 2), Fraction(3, 8)))
        self._assert_parent_bindings(old, (south_id, original_id), (south, first))
        self._assert_parent_bindings(new, (corrected_id, south_id), (corrected, south))

    def test_original_read(self):
        _, pieces = self._versions()
        self.source.close()
        north_id, corrected_id, south_id = self.receive_pieces(*pieces)
        original = self.sign_pair((north_id, south_id))
        corrected = self.sign_pair((corrected_id, south_id))
        self.reopen_center()

        def authorize(action, arg1, _arg2, _database, _trigger):
            if action == sqlite3.SQLITE_READ and arg1 == 'received_pieces':
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        self.center.set_authorizer(authorize)
        self.addCleanup(self.center.set_authorizer, None)
        self.assertEqual(read(self.center, original[0].report_id), original)
        self.assertEqual(read(self.center, corrected[0].report_id), corrected)
        self.assertEqual(self.sign_counts(), (2, 2))

    def test_unknown_report(self):
        pair = self.offline_pair()
        (decision, _receipt) = self.sign_pair(pair)
        with self.assertRaisesRegex(LookupError, 'unknown report'):
            read(self.center, decision.report_id + 100)
        self.assertEqual(self.sign_counts(), (1, 1))

    def test_reopen_after_initialization(self):
        revisions, pieces = self._versions()
        original_id, corrected_id, south_id = self.receive_pieces(*pieces)
        original = self.sign_pair((original_id, south_id))
        corrected = self.sign_pair((corrected_id, south_id))
        self.source.close()
        self.trials.close()
        self.trials = self.open_book('trials', initialize_trials)
        self.source = self.open_book('source', initialize_revisions, initialize_issuance)
        self.reopen_center()
        for revision, piece, receipt_id in zip(revisions, pieces, (original_id, corrected_id, south_id), strict=True):
            self.assertEqual(load_revision(self.source, ROUND, revision.station, revision.revision_id), revision)
            self.assertEqual(self.freeze_revision(revision), piece)
            self.assertEqual(load_receipt(self.center, receipt_id).payload, piece.payload)
        self.assertEqual(read(self.center, original[0].report_id), original)
        self.assertEqual(read(self.center, corrected[0].report_id), corrected)
