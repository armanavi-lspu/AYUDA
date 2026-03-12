"""
Fairness audit module for the AYUDA beneficiary recommendation system.

Checks recommendation outputs for geographic diversity, demographic parity,
and disparate impact to ensure equitable beneficiary selection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


class FairnessAuditor:
    """Comprehensive fairness audit of recommendations.

    Checks:
    - Geographic diversity (>= 80 % of barangays represented)
    - Demographic parity (+/- 15 % difference acceptable)
    - Disparate impact ratio (>= 0.80, four-fifths rule)
    - No systematic group exclusion
    """

    # Thresholds
    GEOGRAPHIC_THRESHOLD = 0.80
    DEMOGRAPHIC_DIFFERENCE_THRESHOLD = 0.15
    DISPARATE_IMPACT_THRESHOLD = 0.80

    def __init__(
        self,
        beneficiaries: List[Dict[str, Any]],
        recommendations: List[Dict[str, Any]],
    ):
        self.beneficiaries = beneficiaries
        self.recommendations = recommendations

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def audit(self) -> Dict[str, Any]:
        """Run the complete fairness audit and return a structured report."""
        geo = self.geographic_fairness()
        demo = self.demographic_fairness()
        di = self.disparate_impact()
        violations = self._find_violations(geo, demo, di)

        all_pass = len(violations) == 0

        return {
            'status': 'PASS' if all_pass else 'FAIL',
            'geographic_fairness': geo,
            'demographic_fairness': demo,
            'disparate_impact': di,
            'violations': violations,
            'overall_fairness_score': self._calc_overall_score(geo, demo, di),
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def geographic_fairness(self) -> Dict[str, Any]:
        """Check geographic diversity of recommendations."""
        total_barangays = set(
            b.get('barangay') for b in self.beneficiaries
            if b.get('barangay')
        )
        rec_barangays = set(
            r.get('barangay') for r in self.recommendations
            if r.get('barangay')
        )

        if not total_barangays:
            return {
                'barangays_represented': 0,
                'barangays_total': 0,
                'representation_percentage': 0,
                'status': 'SKIP',
                'message': 'No barangay data available',
            }

        representation = len(rec_barangays) / len(total_barangays)

        return {
            'barangays_represented': len(rec_barangays),
            'barangays_total': len(total_barangays),
            'representation_percentage': round(representation, 4),
            'status': 'PASS' if representation >= self.GEOGRAPHIC_THRESHOLD else 'FAIL',
            'message': f"Geographic diversity: {representation:.1%} of barangays represented",
            'missing_barangays': sorted(total_barangays - rec_barangays),
        }

    def demographic_fairness(self) -> Dict[str, Any]:
        """Check demographic group representation."""
        groups = {
            'solo_parent': 'is_solo_parent',
            'student': 'is_student',
            'pwd': 'is_pwd',
        }

        if not self.beneficiaries or not self.recommendations:
            return {'groups': {}, 'overall_status': 'SKIP'}

        results: Dict[str, Dict[str, Any]] = {}
        for group_name, field in groups.items():
            pop_rate = sum(
                1 for b in self.beneficiaries if b.get(field)
            ) / len(self.beneficiaries)

            rec_rate = sum(
                1 for r in self.recommendations if r.get(field)
            ) / len(self.recommendations)

            difference = abs(rec_rate - pop_rate)

            results[group_name] = {
                'population_rate': round(pop_rate, 4),
                'recommendation_rate': round(rec_rate, 4),
                'difference': round(difference, 4),
                'status': 'PASS' if difference <= self.DEMOGRAPHIC_DIFFERENCE_THRESHOLD else 'FAIL',
            }

        overall = 'PASS' if all(
            g['status'] == 'PASS' for g in results.values()
        ) else 'FAIL'

        return {'groups': results, 'overall_status': overall}

    def disparate_impact(self) -> Dict[str, Any]:
        """Check four-fifths rule for protected groups.

        The disparate impact ratio for a protected group should not fall
        below 0.80 of the majority group's selection rate.
        """
        if not self.recommendations or not self.beneficiaries:
            return {
                'status': 'SKIP',
                'message': 'Insufficient data for disparate impact analysis',
            }

        # Check PWD as the primary protected group
        results: Dict[str, Dict[str, Any]] = {}
        for field, label in [('is_pwd', 'PWD'), ('is_solo_parent', 'Solo Parent')]:
            total_protected = sum(1 for b in self.beneficiaries if b.get(field))
            total_majority = len(self.beneficiaries) - total_protected

            if total_protected == 0 or total_majority == 0:
                results[label] = {
                    'status': 'SKIP',
                    'message': f'Insufficient {label} data',
                }
                continue

            selected_protected = sum(1 for r in self.recommendations if r.get(field))
            selected_majority = len(self.recommendations) - selected_protected

            protected_rate = selected_protected / total_protected
            majority_rate = selected_majority / total_majority

            ratio = protected_rate / majority_rate if majority_rate > 0 else 1.0

            results[label] = {
                'protected_selection_rate': round(protected_rate, 4),
                'majority_selection_rate': round(majority_rate, 4),
                'ratio': round(ratio, 4),
                'status': 'PASS' if ratio >= self.DISPARATE_IMPACT_THRESHOLD else 'FAIL',
                'message': (
                    f"4/5 rule for {label}: selection ratio {ratio:.2f} "
                    f"vs {self.DISPARATE_IMPACT_THRESHOLD:.2f} threshold"
                ),
            }

        overall = 'PASS' if all(
            r.get('status') in ('PASS', 'SKIP') for r in results.values()
        ) else 'FAIL'

        return {'groups': results, 'overall_status': overall}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_violations(
        self,
        geo: Dict[str, Any],
        demo: Dict[str, Any],
        di: Dict[str, Any],
    ) -> List[str]:
        violations: list[str] = []
        if geo.get('status') == 'FAIL':
            violations.append(
                f"Geographic under-representation: {geo.get('representation_percentage', 0):.1%} "
                f"< {self.GEOGRAPHIC_THRESHOLD:.0%}"
            )
        if demo.get('overall_status') == 'FAIL':
            for name, info in demo.get('groups', {}).items():
                if info.get('status') == 'FAIL':
                    violations.append(
                        f"Demographic parity violation for {name}: "
                        f"difference {info['difference']:.1%} > {self.DEMOGRAPHIC_DIFFERENCE_THRESHOLD:.0%}"
                    )
        if di.get('overall_status') == 'FAIL':
            for name, info in di.get('groups', {}).items():
                if info.get('status') == 'FAIL':
                    violations.append(
                        f"Disparate impact violation for {name}: "
                        f"ratio {info.get('ratio', 0):.2f} < {self.DISPARATE_IMPACT_THRESHOLD}"
                    )
        return violations

    def _calc_overall_score(
        self,
        geo: Dict[str, Any],
        demo: Dict[str, Any],
        di: Dict[str, Any],
    ) -> float:
        """Return 0-1 composite fairness score."""
        scores: list[float] = []

        # Geographic component (40 %)
        geo_pct = geo.get('representation_percentage', 0) or 0
        scores.append(min(geo_pct / self.GEOGRAPHIC_THRESHOLD, 1.0) * 0.40)

        # Demographic parity component (30 %)
        demo_groups = demo.get('groups', {})
        if demo_groups:
            parity_scores = [
                max(0, 1 - g['difference'] / self.DEMOGRAPHIC_DIFFERENCE_THRESHOLD)
                for g in demo_groups.values()
            ]
            scores.append((sum(parity_scores) / len(parity_scores)) * 0.30)

        # Disparate impact component (30 %)
        di_groups = di.get('groups', {})
        di_vals = [
            min(g.get('ratio', 1.0) / self.DISPARATE_IMPACT_THRESHOLD, 1.0)
            for g in di_groups.values()
            if g.get('status') != 'SKIP'
        ]
        if di_vals:
            scores.append((sum(di_vals) / len(di_vals)) * 0.30)

        return round(sum(scores), 4)
