from collections.abc import Iterable
from fractions import Fraction


def parse_weight(value: Fraction | int | str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (Fraction, int, str)):
        raise ValueError('observation weight must be an exact rational number')
    try:
        weight = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError('observation weight must be an exact rational number') from error
    if weight < 0:
        raise ValueError('observation weight must be nonnegative')
    return weight


def validate_unit_mass(weights: Iterable[Fraction]) -> None:
    mass = sum(weights, Fraction(0))
    if mass != 1:
        raise ValueError(f'observation weights must sum to one, got {mass}')
