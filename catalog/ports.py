from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class PortRoster:
    station: str
    ports: tuple[str, ...]


def require_name(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or not value.isprintable():
        raise ValueError(f'{field} must be a nonblank printable string')
    return value


def build_port_roster(station: str, ports: Iterable[str]) -> PortRoster:
    require_name(station, 'station')
    if isinstance(ports, (str, bytes)):
        raise ValueError('ports must be a collection of names')
    try:
        names = tuple(require_name(port, 'port') for port in ports)
    except TypeError as error:
        raise ValueError('ports must be a collection of names') from error
    if len(names) > 4 or len(set(names)) != len(names):
        raise ValueError('a station has at most four distinct public ports')
    return PortRoster(station, tuple(sorted(names)))
