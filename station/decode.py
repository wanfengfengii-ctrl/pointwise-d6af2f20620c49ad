import json

from .bounds_exchange import BOUNDS_VERSION, BoundsStationPiece, decode_bounds_piece
from .exchange import StationPiece, decode_piece


def decode_any(payload: str) -> StationPiece | BoundsStationPiece:
    if not isinstance(payload, str):
        raise ValueError('station piece must be JSON text')
    try:
        envelope = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError('station piece must be JSON text') from error
    if not isinstance(envelope, dict) or 'version' not in envelope:
        raise ValueError('invalid station piece fields')
    if envelope['version'] == BOUNDS_VERSION:
        return decode_bounds_piece(payload)
    return decode_piece(payload)
