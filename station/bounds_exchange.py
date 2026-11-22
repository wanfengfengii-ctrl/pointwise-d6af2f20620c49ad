import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction

from .exchange import Partition

BOUNDS_VERSION = 2


@dataclass(frozen=True)
class BoundsEvidenceRow:
    blocks: Partition
    lower: Fraction
    upper: Fraction


@dataclass(frozen=True)
class BoundsStationPiece:
    issuance_id: str
    round_id: str
    station: str
    revision_id: int
    ports: tuple[str, ...]
    rows: tuple[BoundsEvidenceRow, ...]


def bounds_issuance_identity(round_id: str, station: str, revision_id: int) -> str:
    key = json.dumps([round_id, station, revision_id], separators=(',', ':'))
    return 'v2-' + hashlib.sha256(key.encode('ascii')).hexdigest()


def _rational(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def encode_bounds_piece(piece: BoundsStationPiece) -> str:
    envelope = {
        'version': BOUNDS_VERSION,
        'issuance_id': piece.issuance_id,
        'round_id': piece.round_id,
        'station': piece.station,
        'revision_id': piece.revision_id,
        'ports': piece.ports,
        'rows': [
            {
                'blocks': row.blocks,
                'lower': _rational(row.lower),
                'upper': _rational(row.upper),
            }
            for row in piece.rows
        ],
    }
    return json.dumps(envelope, sort_keys=True, separators=(',', ':'))


def _unique_object(items: list[tuple[str, object]]) -> dict:
    result = dict(items)
    if len(result) != len(items):
        raise ValueError('duplicate JSON field in station piece')
    return result


def _require_fields(value: object, fields: set[str]) -> dict:
    if not isinstance(value, dict) or value.keys() != fields:
        raise ValueError('invalid station piece fields')
    return value


def _names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(name, str) for name in value):
        raise ValueError('port names must be an array of strings')
    return tuple(value)


def _read_fraction(value: object) -> Fraction:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('interval endpoint must contain a numerator and denominator')
    numerator, denominator = value
    if type(numerator) is not int or type(denominator) is not int or denominator <= 0:
        raise ValueError('interval endpoints require integer numerators and positive denominators')
    result = Fraction(numerator, denominator)
    if not 0 <= result <= 1:
        raise ValueError('interval endpoints must lie within [0, 1]')
    return result


def _read_row(value: object) -> BoundsEvidenceRow:
    row = _require_fields(value, {'blocks', 'lower', 'upper'})
    blocks = row['blocks']
    if not isinstance(blocks, list):
        raise ValueError('partition blocks must be an array')
    lower = _read_fraction(row['lower'])
    upper = _read_fraction(row['upper'])
    if lower > upper:
        raise ValueError('partition interval lower bound exceeds upper bound')
    return BoundsEvidenceRow(tuple(_names(block) for block in blocks), lower, upper)


def decode_bounds_piece(payload: str) -> BoundsStationPiece:
    if not isinstance(payload, str):
        raise ValueError('station piece must be JSON text')
    envelope = _require_fields(json.loads(payload, object_pairs_hook=_unique_object), {
        'version', 'issuance_id', 'round_id', 'station', 'revision_id', 'ports', 'rows',
    })
    if envelope['version'] != BOUNDS_VERSION:
        raise ValueError('unsupported station piece version')
    issuance_id, round_id, station = (envelope[key] for key in ('issuance_id', 'round_id', 'station'))
    if any(not isinstance(value, str) or not value for value in (issuance_id, round_id, station)):
        raise ValueError('station piece requires issuance, round and station names')
    revision_id = envelope['revision_id']
    if type(revision_id) is not int or not 1 <= revision_id < 2**63:
        raise ValueError('invalid station revision id')
    rows = envelope['rows']
    if not isinstance(rows, list):
        raise ValueError('evidence rows must be an array')
    return BoundsStationPiece(
        issuance_id, round_id, station, revision_id,
        _names(envelope['ports']), tuple(_read_row(row) for row in rows),
    )
