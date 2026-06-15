"""
Program compatibility scoring for the AYUDA recommendation system.

Determines how well a beneficiary matches a specific program based on
requirements fulfillment, historical approval rates, income alignment,
and priority group matching.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class ProgramCompatibilityScorer:
    """Score how well a beneficiary matches a program."""

    SENIOR_CITIZEN_AGE = 60

    def __init__(self, historical_data: Optional[List[Dict[str, Any]]] = None):
        """Initialize with optional historical application data.

        Args:
            historical_data: List of past application dicts with keys
                ``user_id``, ``program_id``, ``application_status``,
                and beneficiary profile fields.
        """
        self.historical_data = historical_data or []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_fit(
        self,
        beneficiary: Dict[str, Any],
        program: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Calculate program-beneficiary fit score.

        Returns a dict with:
        - ``compatibility_score``: 0-1 composite score
        - ``requirements_met``: fraction of requirements fulfilled
        - ``historical_success_rate``: approval rate for similar profiles
        - ``income_alignment``: how well income matches the program
        - ``priority_match``: alignment with the program's priority group
        - ``program_fit_assessment``: human-readable label
        """
        requirements_match = self._check_requirements_match(beneficiary, program)
        historical_success = self._get_historical_approval_rate(beneficiary, program)
        income_fit = self._calculate_income_fit(beneficiary, program)
        priority_match = self._check_priority_group_match(beneficiary, program)

        compatibility_score = (
            requirements_match * 0.25
            + historical_success * 0.30
            + income_fit * 0.25
            + priority_match * 0.20
        )

        return {
            'compatibility_score': round(compatibility_score, 4),
            'requirements_met': round(requirements_match, 4),
            'historical_success_rate': round(historical_success, 4),
            'income_alignment': round(income_fit, 4),
            'priority_match': round(priority_match, 4),
            'program_fit_assessment': self._generate_fit_assessment(compatibility_score),
        }

    def score_batch(
        self,
        beneficiaries: List[Dict[str, Any]],
        program: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Score multiple beneficiaries against one program.

        Returns the list enriched with ``compatibility`` key.
        """
        results = []
        for b in beneficiaries:
            enriched = dict(b)
            enriched['compatibility'] = self.calculate_fit(b, program)
            results.append(enriched)
        results.sort(
            key=lambda x: x['compatibility']['compatibility_score'], reverse=True
        )
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_requirements_match(
        self,
        beneficiary: Dict[str, Any],
        program: Dict[str, Any],
    ) -> float:
        """Check what fraction of program requirements the beneficiary meets."""
        requirements = program.get('requirements', [])
        if not requirements:
            return 0.9  # Default high match when no requirements specified

        met = 0
        for req in requirements:
            field = req.get('field', '')
            if not field:
                continue
            value = beneficiary.get(field)
            if value is not None and value != '' and value is not False:
                met += 1

        return met / len(requirements) if requirements else 0.9

    def _get_historical_approval_rate(
        self,
        beneficiary: Dict[str, Any],
        program: Dict[str, Any],
    ) -> float:
        """Approval rate for similar beneficiaries in this program."""
        if not self.historical_data:
            return 0.5  # Default 50 % when no history

        program_id = program.get('id')
        if program_id is None:
            return 0.5

        ben_age = beneficiary.get('age') or 30
        age_low = ben_age - 5
        age_high = ben_age + 5

        relevant = [
            h for h in self.historical_data
            if h.get('program_id') == program_id
            and age_low <= (h.get('age') or 0) <= age_high
        ]

        if not relevant:
            return 0.5

        approved = sum(
            1 for h in relevant
            if h.get('application_status') in ('approved', 'completed')
        )
        return approved / len(relevant)

    def _calculate_income_fit(
        self,
        beneficiary: Dict[str, Any],
        program: Dict[str, Any],
    ) -> float:
        """Score how well the beneficiary's income aligns with the program."""
        income = float(beneficiary.get('family_annual_income', 0) or 0)

        # Try to extract income range from the program
        income_range_str = program.get('income_range', '')
        if not income_range_str:
            max_income = program.get('max_income', 400_000)
            if income <= max_income:
                return 1.0
            return max(0, 1 - (income - max_income) / max_income)

        # Parse range string (e.g. "0-250000" or "Below 250,000")
        try:
            cleaned = str(income_range_str).replace(',', '').replace(' ', '')
            if '-' in cleaned:
                parts = cleaned.split('-')
                range_min = float(parts[0])
                range_max = float(parts[1])
            elif cleaned.lower().startswith('below'):
                range_min = 0
                range_max = float(cleaned.lower().replace('below', '').strip())
            else:
                return 0.5  # Unparseable
        except (ValueError, IndexError):
            return 0.5

        if range_min <= income <= range_max:
            return 1.0

        if income < range_min:
            return max(0, 1 - (range_min - income) / max(range_min, 1))
        return max(0, 1 - (income - range_max) / max(range_max, 1))

    def _check_priority_group_match(
        self,
        beneficiary: Dict[str, Any],
        program: Dict[str, Any],
    ) -> float:
        """Check if beneficiary matches the program's priority group."""
        priority_group = (program.get('priority_group') or '').lower()
        if not priority_group:
            return 0.5  # No priority group specified

        tokens = [t.strip() for t in priority_group.split(',') if t.strip()]
        if not tokens:
            return 0.5

        matches = 0
        for token in tokens:
            if 'solo parent' in token and beneficiary.get('is_solo_parent'):
                matches += 1
            elif 'student' in token and beneficiary.get('is_student'):
                matches += 1
            elif ('pwd' in token or 'disability' in token) and beneficiary.get('is_pwd'):
                matches += 1
            elif ('senior' in token or 'elderly' in token):
                if (beneficiary.get('age') or 0) >= self.SENIOR_CITIZEN_AGE:
                    matches += 1
            elif 'low income' in token or 'poor' in token:
                income = float(beneficiary.get('family_annual_income', 0) or 0)
                if income < 250_000:
                    matches += 1

        return matches / len(tokens) if tokens else 0.5

    def _generate_fit_assessment(self, score: float) -> str:
        """Return a human-readable assessment based on score."""
        if score >= 0.80:
            return 'Excellent fit'
        if score >= 0.60:
            return 'Good fit'
        if score >= 0.40:
            return 'Moderate fit'
        if score >= 0.20:
            return 'Low fit'
        return 'Poor fit'
