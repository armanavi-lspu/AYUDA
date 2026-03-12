"""
Explainability module for the AYUDA beneficiary recommendation system.

Generates human-readable explanations for recommendation scores so that
admins and stakeholders understand *why* a beneficiary received their ranking.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class BeneficiaryExplainer:
    """Generate human-readable explanations for recommendation scores."""

    # Income brackets used for plain-language descriptions (PHP annual)
    _INCOME_BRACKETS = [
        (100_000, 'very low income'),
        (250_000, 'low income'),
        (400_000, 'moderate income'),
    ]

    # Default weight map – mirrors score_beneficiaries() in recommender.py
    _DEFAULT_WEIGHTS = {
        'low_income': 0.30,
        'solo_parent': 0.20,
        'student': 0.15,
        'pwd': 0.20,
        'senior_citizen': 0.15,
    }

    SENIOR_CITIZEN_AGE = 60

    def __init__(
        self,
        population: Optional[List[Dict[str, Any]]] = None,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.population = population or []
        self.weights = weights or dict(self._DEFAULT_WEIGHTS)

        # Pre-compute population statistics if available
        self._pop_stats = self._compute_population_stats() if self.population else {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def explain_score(self, beneficiary: Dict[str, Any], score: float) -> Dict[str, Any]:
        """Provide a full breakdown of how *score* was derived.

        Returns a dictionary containing:
        - ``total_score``: the rounded score
        - ``score_breakdown``: per-factor contribution
        - ``plain_english_explanation``: human-readable summary
        - ``compared_to_average``: comparison against population mean
        - ``vulnerability_level``: HIGH / MEDIUM / LOW classification
        """
        income_score = self._income_score(beneficiary)

        breakdown: Dict[str, Dict[str, Any]] = {
            'income_factor': {
                'weight': self.weights.get('low_income', 0.30),
                'beneficiary_value': round(income_score, 4),
                'contribution': round(self.weights.get('low_income', 0.30) * income_score, 4),
            },
            'solo_parent_factor': {
                'weight': self.weights.get('solo_parent', 0.20),
                'beneficiary_value': float(bool(beneficiary.get('is_solo_parent', False))),
                'contribution': round(
                    self.weights.get('solo_parent', 0.20)
                    if beneficiary.get('is_solo_parent') else 0, 4
                ),
            },
            'student_factor': {
                'weight': self.weights.get('student', 0.15),
                'beneficiary_value': float(bool(beneficiary.get('is_student', False))),
                'contribution': round(
                    self.weights.get('student', 0.15)
                    if beneficiary.get('is_student') else 0, 4
                ),
            },
            'pwd_factor': {
                'weight': self.weights.get('pwd', 0.20),
                'beneficiary_value': float(bool(beneficiary.get('is_pwd', False))),
                'contribution': round(
                    self.weights.get('pwd', 0.20)
                    if beneficiary.get('is_pwd') else 0, 4
                ),
            },
            'senior_citizen_factor': {
                'weight': self.weights.get('senior_citizen', 0.15),
                'beneficiary_value': float((beneficiary.get('age') or 0) >= self.SENIOR_CITIZEN_AGE),
                'contribution': round(
                    self.weights.get('senior_citizen', 0.15)
                    if (beneficiary.get('age') or 0) >= self.SENIOR_CITIZEN_AGE else 0, 4
                ),
            },
            'unemployed_factor': {
                'weight': 0.0,  # implicit boost, not a separate weight
                'beneficiary_value': float(not beneficiary.get('is_currently_employed', False)),
                'contribution': 0.0,
            },
        }

        return {
            'total_score': round(score, 4),
            'score_breakdown': breakdown,
            'plain_english_explanation': self._generate_explanation(beneficiary),
            'compared_to_average': self._compare_to_population(beneficiary, score),
            'vulnerability_level': self._assess_vulnerability(beneficiary),
        }

    def explain_batch(
        self,
        scored_beneficiaries: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Attach explanations to each item in a scored list."""
        results = []
        for item in scored_beneficiaries:
            explanation = self.explain_score(item, item.get('score', 0))
            enriched = dict(item)
            enriched['explanation'] = explanation
            results.append(enriched)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _income_score(self, beneficiary: Dict[str, Any]) -> float:
        """Return a 0-1 score where *lower* income yields *higher* value."""
        income = float(beneficiary.get('family_annual_income', 0) or 0)
        if income <= 0:
            return 1.0

        if not self._pop_stats:
            # Without population data, use a simple bracket heuristic
            if income < 100_000:
                return 1.0
            if income < 250_000:
                return 0.75
            if income < 400_000:
                return 0.50
            return 0.25

        max_inc = self._pop_stats.get('max_income', 1) or 1
        min_inc = self._pop_stats.get('min_income', 0)
        income_range = max_inc - min_inc if max_inc > min_inc else 1
        return max(0.0, 1 - (income - min_inc) / income_range)

    def _generate_explanation(self, beneficiary: Dict[str, Any]) -> str:
        """Generate a plain-language summary of vulnerability factors."""
        factors: list[str] = []

        income = float(beneficiary.get('family_annual_income', 0) or 0)
        for threshold, label in self._INCOME_BRACKETS:
            if income < threshold:
                factors.append(label)
                break

        if beneficiary.get('is_solo_parent'):
            factors.append('single parent household')
        if beneficiary.get('is_student'):
            factors.append('currently studying')
        if beneficiary.get('is_pwd'):
            factors.append('person with disability')
        if not beneficiary.get('is_currently_employed'):
            factors.append('not currently employed')
        if (beneficiary.get('age') or 0) >= self.SENIOR_CITIZEN_AGE:
            factors.append('senior citizen')

        if factors:
            return f"Vulnerability indicators: {', '.join(factors)}"
        return "No significant vulnerability indicators detected"

    def _compare_to_population(
        self, beneficiary: Dict[str, Any], score: float
    ) -> Dict[str, Any]:
        """Compare a beneficiary's score against population averages."""
        if not self._pop_stats:
            return {'available': False, 'message': 'No population data loaded'}

        avg_income = self._pop_stats.get('avg_income', 0)
        income = float(beneficiary.get('family_annual_income', 0) or 0)

        return {
            'available': True,
            'population_avg_income': round(avg_income, 2),
            'beneficiary_income': round(income, 2),
            'income_vs_average': (
                'below average' if income < avg_income
                else 'above average' if income > avg_income
                else 'at average'
            ),
            'score': round(score, 4),
        }

    def _assess_vulnerability(self, beneficiary: Dict[str, Any]) -> str:
        """Return HIGH / MEDIUM / LOW vulnerability classification."""
        count = 0
        income = float(beneficiary.get('family_annual_income', 0) or 0)
        if income < 100_000:
            count += 2
        elif income < 250_000:
            count += 1
        if beneficiary.get('is_solo_parent'):
            count += 1
        if beneficiary.get('is_pwd'):
            count += 1
        if beneficiary.get('is_student'):
            count += 1
        if not beneficiary.get('is_currently_employed'):
            count += 1
        if (beneficiary.get('age') or 0) >= self.SENIOR_CITIZEN_AGE:
            count += 1

        if count >= 4:
            return 'HIGH'
        if count >= 2:
            return 'MEDIUM'
        return 'LOW'

    def _compute_population_stats(self) -> Dict[str, float]:
        """Pre-compute population-level statistics."""
        if not self.population:
            return {}
        incomes = [float(b.get('family_annual_income', 0) or 0) for b in self.population]
        return {
            'avg_income': sum(incomes) / len(incomes) if incomes else 0,
            'min_income': min(incomes) if incomes else 0,
            'max_income': max(incomes) if incomes else 0,
            'total': len(self.population),
            'solo_parent_rate': sum(1 for b in self.population if b.get('is_solo_parent')) / len(self.population),
            'student_rate': sum(1 for b in self.population if b.get('is_student')) / len(self.population),
            'pwd_rate': sum(1 for b in self.population if b.get('is_pwd')) / len(self.population),
        }
