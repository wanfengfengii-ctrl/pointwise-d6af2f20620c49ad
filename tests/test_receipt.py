import json
from dataclasses import replace
from fractions import Fraction

from receipt import receive
from receipt.intake import load_receipt
from station.exchange import EvidenceRow, decode_piece, encode_piece
from tests import LabCase


class ReceiptTests(LabCase):
    def test_offline_receipt(self):
        north, south = self.freeze_sample()
        self.source.close()
        north_id, south_id = self.receive_pieces(north, south)
        for receipt_id, issued in ((north_id, north), (south_id, south)):
            record = load_receipt(self.center, receipt_id)
            self.assertEqual(record.payload, issued.payload)
            self.assertEqual(record.piece.issuance_id, issued.issuance_id)
            self.assertEqual(record.piece.revision_id, issued.revision_id)

    def test_identical_replay(self):
        north, _ = self.freeze_sample()
        self.source.close()
        first = receive(self.trials, self.center, north.payload)
        reordered = json.dumps(json.loads(north.payload), indent=2)
        self.assertEqual(receive(self.trials, self.center, reordered), first)
        self.assertEqual(receive(self.trials, self.center, north.payload), first)
        self.assertEqual(load_receipt(self.center, first).payload, north.payload)
        self.assertEqual(self.center.execute('SELECT count(*) FROM received_pieces').fetchone()[0], 1)

    def test_conflicting_reissue(self):
        north, south = self.freeze_sample()
        self.source.close()
        north_id, south_id = self.receive_pieces(north, south)
        original = decode_piece(north.payload)
        conflict = replace(original, rows=(EvidenceRow((('A',), ('B',), ('P',)), Fraction(1)),))
        with self.assertRaisesRegex(ValueError, 'conflicting content'):
            receive(self.trials, self.center, encode_piece(conflict))
        self.assertEqual(self.center.execute('SELECT count(*) FROM received_pieces').fetchone()[0], 2)
        self.assertEqual(load_receipt(self.center, north_id).payload, north.payload)
        result, receipt = self.sign_pair((north_id, south_id))
        self.assertEqual(result.probability, Fraction(1, 2))
        self.assertEqual(result.verdict, 'pass')
        self.assertEqual(result.parents[0].issuance_id, north.issuance_id)
        self.assertEqual(receipt.report_id, result.report_id)

    def test_malformed_law(self):
        north, _ = self.freeze_sample()
        piece = decode_piece(north.payload)
        first = EvidenceRow((('A',), ('B',), ('P',)), Fraction(1, 2))
        second = EvidenceRow((('A', 'B', 'P'),), Fraction(1, 2))
        bad_rows = (
            (), (first,), (first, first), (second, first),
            (EvidenceRow((('A', 'B'), ('B', 'P')), Fraction(1)),),
            (EvidenceRow((('A', 'P'),), Fraction(1)),),
            (EvidenceRow((('B', 'A', 'P'),), Fraction(1)),),
            (replace(first, mass=Fraction(-1)), replace(second, mass=Fraction(2))),
        )
        for rows in bad_rows:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                receive(self.trials, self.center, encode_piece(replace(piece, rows=rows)))
        self.assertEqual(self.center.execute('SELECT count(*) FROM received_pieces').fetchone()[0], 0)
        self.assertEqual(self.receive_pieces(north), (1,))

    def test_bad_binding_or_envelope(self):
        north, _ = self.freeze_sample()
        for field, value in (('version', True), ('version', 2), ('ports', ['A', 'B']), ('revision_id', 99)):
            raw = json.loads(north.payload)
            raw[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                receive(self.trials, self.center, json.dumps(raw))
        raw = json.loads(north.payload)
        raw['rows'][0]['mass'][1] = 0
        with self.assertRaises(ValueError):
            receive(self.trials, self.center, json.dumps(raw))
        self.assertEqual(self.center.execute('SELECT count(*) FROM received_pieces').fetchone()[0], 0)
