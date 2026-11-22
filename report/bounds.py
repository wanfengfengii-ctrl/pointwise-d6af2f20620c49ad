from math import gcd
from fractions import Fraction

from catalog.requests import SamplingRequest
from receipt.selection import SelectedPair
from station.bounds_exchange import BoundsStationPiece
from .network import both_targets_reachable

Distribution = tuple[tuple[tuple[tuple[str, ...], ...], Fraction], ...]


def _point_law(piece) -> tuple[tuple, tuple[Fraction, ...], tuple[Fraction, ...], bool]:
    if isinstance(piece, BoundsStationPiece):
        rows = piece.rows
        lower = tuple(row.lower for row in rows)
        upper = tuple(row.upper for row in rows)
        return rows, lower, upper, False
    rows = piece.rows
    masses = tuple(row.mass for row in rows)
    return rows, masses, masses, True


def _scale(lower: tuple[Fraction, ...], upper: tuple[Fraction, ...]):
    """Lift rational endpoints to a shared integer denominator.

    Every feasible allocation (and therefore every vertex and every greedy
    optimum) has coordinates in (1/D)Z, so all optimization can run on
    integers and be converted back to Fractions only for the witnesses.
    """
    denominator = 1
    for value in (*lower, *upper):
        denominator = denominator * value.denominator // gcd(denominator, value.denominator)
    low = tuple(denominator * value.numerator // value.denominator for value in lower)
    high = tuple(denominator * value.numerator // value.denominator for value in upper)
    return denominator, low, high


def integer_capped_simplex_vertices(low, high, total):
    """Vertices of {z in Z^n: low <= z <= high, sum(z) = total}."""
    count = len(low)
    residual = total - sum(low)
    if residual < 0:
        raise ValueError('interval lower bounds exceed one')
    capacities = tuple(high[i] - low[i] for i in range(count))
    if sum(capacities) < residual:
        raise ValueError('interval upper bounds cannot reach one')
    vertices: set[tuple[int, ...]] = set()
    indices = tuple(range(count))

    def record(interior: int | None, saturated: frozenset[int]) -> None:
        point = list(low)
        used = 0
        for index in saturated:
            point[index] = high[index]
            used += capacities[index]
        if interior is None:
            if used == residual:
                vertices.add(tuple(point))
            return
        slack = residual - used
        if 0 < slack < capacities[interior]:
            point[interior] = low[interior] + slack
            vertices.add(tuple(point))

    for interior in (*indices, None):
        others = tuple(index for index in indices if index != interior)
        for mask in range(1 << len(others)):
            saturated = frozenset(
                others[position]
                for position in range(len(others))
                if (mask >> position) & 1
            )
            record(interior, saturated)
    if not vertices:
        raise ValueError('interval polytope has no vertices')
    return tuple(sorted(vertices))


def capped_simplex_vertices(lower, upper) -> tuple[tuple[Fraction, ...], ...]:
    denominator, low, high = _scale(lower, upper)
    total = denominator
    vertices = integer_capped_simplex_vertices(low, high, total)
    return tuple(tuple(Fraction(value, denominator) for value in point) for point in vertices)


def integer_greedy_extreme(coefficients, low, high, total, maximize: bool) -> tuple[int, ...]:
    """Integer water-filling optimum of c.z over the integer capped simplex."""
    point = list(low)
    remaining = total - sum(low)
    order = sorted(range(len(low)), key=lambda index: coefficients[index],
                   reverse=maximize)
    for index in order:
        take = min(remaining, high[index] - low[index])
        point[index] += take
        remaining -= take
        if remaining == 0:
            break
    if remaining != 0:
        raise ValueError('interval polytope cannot sum to one')
    return tuple(point)


def _as_distribution(rows, integer_point, denominator) -> Distribution:
    ordered = sorted(
        ((row.blocks, Fraction(integer_point[index], denominator))
         for index, row in enumerate(rows) if integer_point[index] > 0),
        key=lambda item: item[0],
    )
    return tuple(ordered)


def _reach_matrix(first_rows, second_rows, request: SamplingRequest):
    return tuple(
        tuple(
            1 if both_targets_reachable(request, first.blocks, second.blocks) else 0
            for second in second_rows
        )
        for first in first_rows
    )


def bounds_supply_extrema(
    pair: SelectedPair, request: SamplingRequest,
) -> dict:
    first_piece, second_piece = pair.first.piece, pair.second.piece
    first_rows, first_lower, first_upper, first_point = _point_law(first_piece)
    second_rows, second_lower, second_upper, second_point = _point_law(second_piece)

    first_denominator, first_low, first_high = _scale(first_lower, first_upper)
    second_denominator, second_low, second_high = _scale(second_lower, second_upper)

    first_vertices = integer_capped_simplex_vertices(
        first_low, first_high, first_denominator,
    )
    second_vertices = integer_capped_simplex_vertices(
        second_low, second_high, second_denominator,
    )
    reach = _reach_matrix(first_rows, second_rows, request)
    first_count, second_count = len(first_rows), len(second_rows)
    # x^T R y = numerator / (D1 * D2); compare the integer numerators directly.
    scale = first_denominator * second_denominator

    lower_num = upper_num = None
    first_low_point = first_high_point = None
    second_low_point = second_high_point = None

    def consider(first_point, second_point) -> None:
        nonlocal lower_num, upper_num
        nonlocal first_low_point, first_high_point
        nonlocal second_low_point, second_high_point
        numerator = 0
        for i in range(first_count):
            xi = first_point[i]
            if xi == 0:
                continue
            row = reach[i]
            for j in range(second_count):
                if row[j]:
                    numerator += xi * second_point[j]
        if lower_num is None or numerator < lower_num:
            lower_num, first_low_point, second_low_point = (
                numerator, first_point, second_point,
            )
        if upper_num is None or numerator > upper_num:
            upper_num, first_high_point, second_high_point = (
                numerator, first_point, second_point,
            )

    if len(first_vertices) <= len(second_vertices):
        for first_point in first_vertices:
            coefficients = tuple(
                sum(reach[i][j] * first_point[i] for i in range(first_count))
                for j in range(second_count)
            )
            consider(first_point, integer_greedy_extreme(
                coefficients, second_low, second_high, second_denominator, False))
            consider(first_point, integer_greedy_extreme(
                coefficients, second_low, second_high, second_denominator, True))
    else:
        for second_point in second_vertices:
            coefficients = tuple(
                sum(reach[i][j] * second_point[j] for j in range(second_count))
                for i in range(first_count)
            )
            consider(integer_greedy_extreme(
                coefficients, first_low, first_high, first_denominator, False),
                second_point)
            consider(integer_greedy_extreme(
                coefficients, first_low, first_high, first_denominator, True),
                second_point)

    return {
        'lower': Fraction(lower_num, scale),
        'upper': Fraction(upper_num, scale),
        'lower_witness': (
            _as_distribution(first_rows, first_low_point, first_denominator),
            _as_distribution(second_rows, second_low_point, second_denominator),
        ),
        'upper_witness': (
            _as_distribution(first_rows, first_high_point, first_denominator),
            _as_distribution(second_rows, second_high_point, second_denominator),
        ),
    }


def back_substitute(pair: SelectedPair, request: SamplingRequest, witness) -> Fraction:
    """Re-evaluate the supply rate from a stored witness, including omitted zero rows."""
    first_piece, second_piece = pair.first.piece, pair.second.piece
    first_mass = dict(witness[0])
    second_mass = dict(witness[1])
    total = Fraction(0)
    for first_row in first_piece.rows:
        for second_row in second_piece.rows:
            if both_targets_reachable(request, first_row.blocks, second_row.blocks):
                total += first_mass.get(first_row.blocks, Fraction(0)) * \
                    second_mass.get(second_row.blocks, Fraction(0))
    return total
