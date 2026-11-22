import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction

Partition = tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class EvidenceRow:
    blocks: Partition
    mass: Fraction


@dataclass(frozen=True)
class StationPiece:
    issuance_id: str
    round_id: str
    station: str
    revision_id: int
    ports: tuple[str, ...]
    rows: tuple[EvidenceRow, ...]


def issuance_identity(round_id: str, station: str, revision_id: int) -> str:
    key = json.dumps([round_id, station, revision_id], separators=(',', ':'))
    return 'v1-' + hashlib.sha256(key.encode('ascii')).hexdigest()


def encode_piece(piece: StationPiece) -> str:
    envelope = {
        'version': 1,
        'issuance_id': piece.issuance_id,
        'round_id': piece.round_id,
        'station': piece.station,
        'revision_id': piece.revision_id,
        'ports': piece.ports,
        'rows': [
            {'blocks': row.blocks, 'mass': [row.mass.numerator, row.mass.denominator]}
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


def _read_row(value: object) -> EvidenceRow:
    row = _require_fields(value, {'blocks', 'mass'})
    blocks, mass = row['blocks'], row['mass']
    if not isinstance(blocks, list):
        raise ValueError('partition blocks must be an array')
    if not isinstance(mass, list) or len(mass) != 2:
        raise ValueError('mass must contain a numerator and denominator')
    numerator, denominator = mass
    if type(numerator) is not int or type(denominator) is not int or denominator <= 0:
        raise ValueError('mass requires an integer numerator and positive integer denominator')
    return EvidenceRow(tuple(_names(block) for block in blocks), Fraction(numerator, denominator))


def decode_piece(payload: str) -> StationPiece:
    if not isinstance(payload, str):
        raise ValueError('station piece must be JSON text')
    envelope = _require_fields(json.loads(payload, object_pairs_hook=_unique_object), {
        'version', 'issuance_id', 'round_id', 'station', 'revision_id', 'ports', 'rows',
    })
    if type(envelope['version']) is not int or envelope['version'] != 1:
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
    return StationPiece(
        issuance_id, round_id, station, revision_id,
        _names(envelope['ports']), tuple(_read_row(row) for row in rows),
    )
