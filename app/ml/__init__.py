"""
Machine learning modules for the AYUDA beneficiary recommendation system.

Provides explainability, fairness auditing, program compatibility scoring,
and weight optimization capabilities.
"""

from app.ml.explainer import BeneficiaryExplainer
from app.ml.fairness_auditor import FairnessAuditor
from app.ml.program_compatibility import ProgramCompatibilityScorer
from app.ml.weight_optimizer import WeightOptimizer
