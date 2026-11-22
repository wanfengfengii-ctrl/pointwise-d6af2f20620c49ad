import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from catalog import initialize_trials
from demo import ROUND, seed_sample
from observations import initialize_revisions
from receipt import initialize_receipts, receive
from report import initialize_decisions, sign
from station import initialize_issuance, issue


class LabCase(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='riverbend-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.trials = self.open_book('trials', initialize_trials)
        self.source = self.open_book('source', initialize_revisions, initialize_issuance)
        self.center = self.open_book('center', initialize_receipts, initialize_decisions)

    def open_book(self, name, *initializers):
        db = sqlite3.connect(self.root / f'{name}.sqlite3')
        self.addCleanup(db.close)
        for initialize in initializers:
            initialize(db)
        return db

    def reopen_center(self):
        self.center.close()
        self.center = self.open_book('center', initialize_receipts, initialize_decisions)

    def freeze_revision(self, revision):
        return issue(self.trials, self.source, revision.round_id, revision.station, revision.revision_id)

    def freeze_sample(self, round_id=ROUND):
        north, south = seed_sample(self.trials, self.source, round_id)
        return self.freeze_revision(north), self.freeze_revision(south)

    def receive_pieces(self, *pieces):
        return tuple(receive(self.trials, self.center, piece.payload) for piece in pieces)

    def offline_pair(self):
        pieces = self.freeze_sample()
        self.source.close()
        return self.receive_pieces(*pieces)

    def sign_pair(self, receipt_ids, entry='P', targets=('A', 'B'), threshold='1/2'):
        return sign(self.trials, self.center, receipt_ids, entry, targets, threshold)

    def sign_counts(self):
        decisions = self.center.execute('SELECT count(*) FROM decisions').fetchone()[0]
        receipts = self.center.execute('SELECT count(*) FROM success_receipts').fetchone()[0]
        return decisions, receipts
