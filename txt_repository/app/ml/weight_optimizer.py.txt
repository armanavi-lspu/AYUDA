"""
Weight optimization framework for the AYUDA recommendation system.

Uses grid search over priority weight combinations to find configurations
that best satisfy multiple objectives (coverage, equity, efficiency).
"""

from __future__ import annotations

from itertools import product
from typing import Any, Dict, List, Optional, Set

import numpy as np


class WeightOptimizer:
    """Optimize recommendation weights for multiple objectives."""

    def __init__(
        self,
        beneficiaries: List[Dict[str, Any]],
        ground_truth_approvals: Optional[List[int]] = None,
    ):
        self.beneficiaries = beneficiaries
        self.ground_truth: Set[int] = (
            set(ground_truth_approvals) if ground_truth_approvals else set()
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize_weights(
        self,
        objectives: Optional[List[str]] = None,
        weight_ranges: Optional[Dict[str, List[float]]] = None,
        top_n: int = 5,
    ) -> Dict[str, Any]:
        """Find optimal weight configuration via grid search.

        Args:
            objectives: Subset of ``['coverage', 'equity', 'efficiency', 'transparency']``.
            weight_ranges: Per-factor candidate weight values to search.
            top_n: Number of top configurations to return.

        Returns:
            Dict with ``optimal_weights``, ``best_score``, and ``top_configs``.
        """
        if objectives is None:
            objectives = ['coverage', 'equity', 'efficiency']

        if weight_ranges is None:
            weight_ranges = {
                'low_income': [0.25, 0.30, 0.40, 0.50],
                'solo_parent': [0.10, 0.20, 0.30, 0.40],
                'student': [0.05, 0.10, 0.20, 0.30],
                'pwd': [0.10, 0.20, 0.30, 0.40],
                'senior_citizen': [0.05, 0.10, 0.15, 0.20],
            }

        best_config: Optional[Dict[str, float]] = None
        best_score = -np.inf
        all_results: list[Dict[str, Any]] = []

        keys = list(weight_ranges.keys())
        for combo in product(*[weight_ranges[k] for k in keys]):
            weights = dict(zip(keys, combo))

            # Normalize to sum 1
            total = sum(weights.values())
            if total <= 0:
                continue
            weights = {k: v / total for k, v in weights.items()}

            metrics = self._evaluate_weights(weights, objectives)
            combined_score = metrics['combined_score']

            all_results.append({
                'weights': weights,
                'metrics': metrics,
                'combined_score': round(combined_score, 6),
            })

            if combined_score > best_score:
                best_score = combined_score
                best_config = weights

        all_results.sort(key=lambda x: x['combined_score'], reverse=True)

        return {
            'optimal_weights': best_config,
            'best_score': round(best_score, 6),
            'top_configs': all_results[:top_n],
            'total_evaluated': len(all_results),
            'objectives': objectives,
        }

    # ------------------------------------------------------------------
    # Evaluation helpers
    # ------------------------------------------------------------------

    def _evaluate_weights(
        self,
        weights: Dict[str, float],
        objectives: List[str],
    ) -> Dict[str, Any]:
        """Score a weight configuration against the requested objectives."""
        score = 0.0
        metrics: Dict[str, Any] = {}

        if 'coverage' in objectives and self.ground_truth:
            coverage = self._calc_coverage(weights)
            metrics['coverage'] = round(coverage, 6)
            score += coverage * 0.35

        if 'equity' in objectives:
            equity = self._calc_equity(weights)
            metrics['equity'] = round(equity, 6)
            score += equity * 0.35

        if 'efficiency' in objectives:
            efficiency = self._calc_efficiency(weights)
            metrics['efficiency'] = round(efficiency, 6)
            score += efficiency * 0.20

        if 'transparency' in objectives:
            transparency = self._calc_transparency(weights)
            metrics['transparency'] = round(transparency, 6)
            score += transparency * 0.10

        metrics['combined_score'] = round(score, 6)
        return metrics

    def _calc_coverage(self, weights: Dict[str, float]) -> float:
        """Recall of known true beneficiaries."""
        if not self.ground_truth:
            return 0.5

        scored = self._score_with_weights(weights)
        # Take top K = |ground_truth| as predictions
        k = len(self.ground_truth)
        top_k_ids = {b['user_id'] for b in scored[:k]}
        tp = len(top_k_ids & self.ground_truth)
        return tp / len(self.ground_truth)

    def _calc_equity(self, weights: Dict[str, float]) -> float:
        """Measure how evenly the scoring distributes across demographic groups."""
        scored = self._score_with_weights(weights)
        if not scored:
            return 0.0

        n = min(75, len(scored))
        top = scored[:n]

        rates: list[float] = []
        for field in ('is_solo_parent', 'is_student', 'is_pwd'):
            pop_rate = sum(1 for b in self.beneficiaries if b.get(field)) / len(self.beneficiaries) if self.beneficiaries else 0
            rec_rate = sum(1 for b in top if b.get(field)) / len(top) if top else 0
            diff = abs(rec_rate - pop_rate)
            rates.append(max(0, 1 - diff / 0.15))  # 0.15 = threshold

        # Geographic diversity
        total_bar = len(set(b.get('barangay') for b in self.beneficiaries if b.get('barangay')))
        rec_bar = len(set(b.get('barangay') for b in top if b.get('barangay')))
        geo_score = (rec_bar / total_bar) if total_bar > 0 else 0.5
        rates.append(min(geo_score / 0.80, 1.0))  # 0.80 = threshold

        return sum(rates) / len(rates) if rates else 0.0

    def _calc_efficiency(self, weights: Dict[str, float]) -> float:
        """Measure how concentrated scores are at the top — well-separated best candidates."""
        scored = self._score_with_weights(weights)
        if len(scored) < 2:
            return 0.5

        scores = [b['score'] for b in scored]
        score_range = max(scores) - min(scores)
        if score_range <= 0:
            return 0.0

        # Gini-like coefficient: more spread = better differentiation
        mean_score = sum(scores) / len(scores)
        mad = sum(abs(s - mean_score) for s in scores) / len(scores)
        return min(mad / mean_score if mean_score > 0 else 0, 1.0)

    def _calc_transparency(self, weights: Dict[str, float]) -> float:
        """Prefer weight distributions that are more uniform (easier to explain)."""
        values = list(weights.values())
        if not values:
            return 0.0
        mean_w = sum(values) / len(values)
        max_dev = max(abs(v - mean_w) for v in values)
        # Lower deviation = higher transparency
        return max(0, 1 - max_dev / mean_w) if mean_w > 0 else 0.0

    # ------------------------------------------------------------------
    # Scoring helper
    # ------------------------------------------------------------------

    def _score_with_weights(
        self, weights: Dict[str, float]
    ) -> List[Dict[str, Any]]:
        """Score beneficiaries with given weights (lightweight, no sklearn)."""
        incomes = [float(b.get('family_annual_income', 0) or 0) for b in self.beneficiaries]
        max_inc = max(incomes) if incomes else 1
        min_inc = min(incomes) if incomes else 0
        inc_range = max_inc - min_inc if max_inc > min_inc else 1

        scored: list[Dict[str, Any]] = []
        for b in self.beneficiaries:
            income = float(b.get('family_annual_income', 0) or 0)
            income_score = 1 - (income - min_inc) / inc_range if inc_range > 0 else 0.5

            score = weights.get('low_income', 0.3) * income_score
            if b.get('is_solo_parent'):
                score += weights.get('solo_parent', 0.2)
            if b.get('is_student'):
                score += weights.get('student', 0.15)
            if b.get('is_pwd'):
                score += weights.get('pwd', 0.2)
            if (b.get('age') or 0) >= 60:
                score += weights.get('senior_citizen', 0.15)

            entry = dict(b)
            entry['score'] = round(score, 6)
            scored.append(entry)

        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored
