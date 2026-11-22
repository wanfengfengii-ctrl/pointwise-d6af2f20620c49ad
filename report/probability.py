from fractions import Fraction

from catalog.requests import SamplingRequest
from receipt.selection import SelectedPair
from .network import both_targets_reachable


def joint_supply_probability(pair: SelectedPair, request: SamplingRequest) -> Fraction:
    probability = Fraction(0)
    for first in pair.first.piece.rows:
        for second in pair.second.piece.rows:
            if both_targets_reachable(request, first.blocks, second.blocks):
                probability += first.mass * second.mass
    return probability


def passes_threshold(probability: Fraction, request: SamplingRequest) -> bool:
    return probability >= request.threshold
