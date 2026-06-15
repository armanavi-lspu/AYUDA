"""
Recommender system configuration framework for AYUDA.

Provides validated, program-specific parameter configurations for the
content-based beneficiary recommendation engine. Each configuration
encodes domain knowledge about a specific program type (e.g. extreme
poverty relief vs. youth scholarships) so that recommendations balance
equity, effectiveness, and transparency.

Usage:
    from app.config import ConfigFactory

    config = ConfigFactory.get_config('extreme_poverty')
    results = get_recommendations(data, **config.to_kwargs())
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Absolute ceiling for income values (PHP)
_MAX_INCOME_CEILING = 10_000_000

# Valid priority weight keys (must match score_beneficiaries in recommender.py)
_VALID_WEIGHT_KEYS = frozenset([
    'low_income', 'solo_parent', 'student', 'pwd', 'senior_citizen',
])

# Where JSON config snapshots are persisted on disk
_CONFIG_STORE_DIR = os.path.join('instance', 'recommender_configs')


# ---------------------------------------------------------------------------
# Base configuration
# ---------------------------------------------------------------------------

class RecommenderConfig:
    """Base configuration for the recommendation system.

    All parameters are validated on construction.  Subclasses override
    ``_defaults()`` to supply program-specific values.
    """

    # -- construction -------------------------------------------------------

    def __init__(
        self,
        *,
        max_beneficiaries: int = 50,
        min_income: float = 0,
        max_income: float = _MAX_INCOME_CEILING,
        priority_barangays: Optional[List[str]] = None,
        solo_parent_priority: bool = False,
        student_priority: bool = False,
        pwd_priority: bool = False,
        senior_citizen_priority: bool = False,
        priority_weights: Optional[Dict[str, float]] = None,
        description: str = '',
    ):
        self.max_beneficiaries = max_beneficiaries
        self.min_income = float(min_income)
        self.max_income = float(max_income)
        self.priority_barangays = list(priority_barangays) if priority_barangays else None
        self.solo_parent_priority = bool(solo_parent_priority)
        self.student_priority = bool(student_priority)
        self.pwd_priority = bool(pwd_priority)
        self.senior_citizen_priority = bool(senior_citizen_priority)
        self.priority_weights = dict(priority_weights) if priority_weights else None
        self.description = description

        self.validate()

    # -- validation ---------------------------------------------------------

    def validate(self) -> None:
        """Validate all parameters, raising ``ValueError`` on problems."""
        errors: list[str] = []

        # max_beneficiaries
        if not isinstance(self.max_beneficiaries, int) or self.max_beneficiaries < 1:
            errors.append('max_beneficiaries must be a positive integer')
        if isinstance(self.max_beneficiaries, int) and self.max_beneficiaries > 500:
            errors.append('max_beneficiaries must not exceed 500')

        # income range
        if self.min_income < 0:
            errors.append('min_income must be >= 0')
        if self.max_income > _MAX_INCOME_CEILING:
            errors.append(f'max_income must not exceed {_MAX_INCOME_CEILING:,}')
        if self.min_income > self.max_income:
            errors.append('min_income must be <= max_income')

        # priority_barangays
        if self.priority_barangays is not None:
            if not isinstance(self.priority_barangays, list):
                errors.append('priority_barangays must be a list of strings or None')
            elif not all(isinstance(b, str) and b.strip() for b in self.priority_barangays):
                errors.append('priority_barangays entries must be non-empty strings')

        # priority_weights
        if self.priority_weights is not None:
            unknown = set(self.priority_weights) - _VALID_WEIGHT_KEYS
            if unknown:
                errors.append(f'Unknown priority_weights keys: {unknown}')
            for key, val in self.priority_weights.items():
                if not isinstance(val, (int, float)) or val < 0:
                    errors.append(f'priority_weights[{key!r}] must be a non-negative number')

        if errors:
            raise ValueError(
                'Invalid RecommenderConfig:\n  - ' + '\n  - '.join(errors)
            )

    # -- serialization ------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary of all parameters."""
        return {
            'config_type': type(self).__name__,
            'max_beneficiaries': self.max_beneficiaries,
            'min_income': self.min_income,
            'max_income': self.max_income,
            'priority_barangays': self.priority_barangays,
            'solo_parent_priority': self.solo_parent_priority,
            'student_priority': self.student_priority,
            'pwd_priority': self.pwd_priority,
            'senior_citizen_priority': self.senior_citizen_priority,
            'priority_weights': self.priority_weights,
            'description': self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RecommenderConfig':
        """Construct a config from a dictionary (e.g. loaded from JSON).

        The ``config_type`` key is ignored — the caller picks which class
        to instantiate.  Unknown keys are silently dropped.
        """
        known = {
            'max_beneficiaries', 'min_income', 'max_income',
            'priority_barangays', 'solo_parent_priority',
            'student_priority', 'pwd_priority', 'senior_citizen_priority',
            'priority_weights', 'description',
        }
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    def to_kwargs(self) -> Dict[str, Any]:
        """Return a dict suitable for ``get_recommendations(**config.to_kwargs())``."""
        kw: Dict[str, Any] = {
            'max_beneficiaries': self.max_beneficiaries,
            'min_income': self.min_income,
            'max_income': self.max_income,
            'solo_parent_priority': self.solo_parent_priority,
            'student_priority': self.student_priority,
            'pwd_priority': self.pwd_priority,
            'senior_citizen_priority': self.senior_citizen_priority,
        }
        if self.priority_barangays is not None:
            kw['priority_barangays'] = self.priority_barangays
        return kw

    # -- copy / merge -------------------------------------------------------

    def copy(self, **overrides: Any) -> 'RecommenderConfig':
        """Return a new config with selected fields overridden."""
        data = self.to_dict()
        data.pop('config_type', None)
        data.update(overrides)
        return type(self)(**data)

    # -- dunder -------------------------------------------------------------

    def __repr__(self) -> str:
        parts = [f'{type(self).__name__}(']
        for key in ('max_beneficiaries', 'min_income', 'max_income',
                     'solo_parent_priority', 'student_priority',
                     'pwd_priority', 'senior_citizen_priority'):
            parts.append(f'  {key}={getattr(self, key)!r},')
        if self.priority_barangays:
            parts.append(f'  priority_barangays={self.priority_barangays!r},')
        if self.priority_weights:
            parts.append(f'  priority_weights={self.priority_weights!r},')
        parts.append(')')
        return '\n'.join(parts)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RecommenderConfig):
            return NotImplemented
        return self.to_dict() == other.to_dict()


# ---------------------------------------------------------------------------
# Pre-defined program-specific configurations
# ---------------------------------------------------------------------------

class BalancedConfig(RecommenderConfig):
    """General-purpose balanced assistance programs.

    Moderate beneficiary cap with all vulnerable-group priorities enabled
    and the full income spectrum considered.
    """

    def __init__(self, **overrides: Any):
        defaults: Dict[str, Any] = {
            'max_beneficiaries': 75,
            'min_income': 0,
            'max_income': 400_000,
            'solo_parent_priority': True,
            'student_priority': True,
            'pwd_priority': True,
            'senior_citizen_priority': True,
            'priority_weights': {
                'low_income': 0.25,
                'solo_parent': 0.20,
                'student': 0.15,
                'pwd': 0.20,
                'senior_citizen': 0.20,
            },
            'description': 'Balanced configuration for general assistance programs',
        }
        defaults.update(overrides)
        super().__init__(**defaults)


class ExtremePovertyConfig(RecommenderConfig):
    """Emergency relief and cash assistance for the poorest households.

    Higher beneficiary cap, tighter income ceiling, and heavy weighting
    on low income.
    """

    def __init__(self, **overrides: Any):
        defaults: Dict[str, Any] = {
            'max_beneficiaries': 120,
            'min_income': 0,
            'max_income': 200_000,
            'solo_parent_priority': True,
            'student_priority': False,
            'pwd_priority': True,
            'senior_citizen_priority': True,
            'priority_weights': {
                'low_income': 0.40,
                'solo_parent': 0.20,
                'student': 0.05,
                'pwd': 0.20,
                'senior_citizen': 0.15,
            },
            'description': 'Emergency relief / cash assistance targeting extreme poverty',
        }
        defaults.update(overrides)
        super().__init__(**defaults)


class YouthFocusConfig(RecommenderConfig):
    """Education scholarships and skills-training programs.

    Smaller cohort with heavy student weighting and a wider income band
    to include near-poor youth.
    """

    def __init__(self, **overrides: Any):
        defaults: Dict[str, Any] = {
            'max_beneficiaries': 50,
            'min_income': 0,
            'max_income': 600_000,
            'solo_parent_priority': True,
            'student_priority': True,
            'pwd_priority': False,
            'senior_citizen_priority': False,
            'priority_weights': {
                'low_income': 0.20,
                'solo_parent': 0.15,
                'student': 0.40,
                'pwd': 0.10,
                'senior_citizen': 0.15,
            },
            'description': 'Youth-focused scholarships and skills training',
        }
        defaults.update(overrides)
        super().__init__(**defaults)


class PWDFocusConfig(RecommenderConfig):
    """Programs specifically for persons with disabilities.

    Smaller cohort, strong PWD weighting, and consideration for
    solo-parent PWD households.
    """

    def __init__(self, **overrides: Any):
        defaults: Dict[str, Any] = {
            'max_beneficiaries': 40,
            'min_income': 0,
            'max_income': 500_000,
            'solo_parent_priority': True,
            'student_priority': False,
            'pwd_priority': True,
            'senior_citizen_priority': False,
            'priority_weights': {
                'low_income': 0.20,
                'solo_parent': 0.15,
                'student': 0.05,
                'pwd': 0.45,
                'senior_citizen': 0.15,
            },
            'description': 'Programs for persons with disabilities',
        }
        defaults.update(overrides)
        super().__init__(**defaults)


class LivelihoodConfig(RecommenderConfig):
    """Income-generation and livelihood programs.

    Larger cohort, moderate income ceiling, solo-parent priority for
    breadwinner support.
    """

    def __init__(self, **overrides: Any):
        defaults: Dict[str, Any] = {
            'max_beneficiaries': 100,
            'min_income': 0,
            'max_income': 500_000,
            'solo_parent_priority': True,
            'student_priority': False,
            'pwd_priority': False,
            'senior_citizen_priority': False,
            'priority_weights': {
                'low_income': 0.35,
                'solo_parent': 0.25,
                'student': 0.05,
                'pwd': 0.15,
                'senior_citizen': 0.20,
            },
            'description': 'Livelihood and income-generation programs',
        }
        defaults.update(overrides)
        super().__init__(**defaults)


class SeniorCitizenConfig(RecommenderConfig):
    """Programs for senior citizens (age >= 60).

    Moderate cohort with strong senior-citizen weighting.
    """

    def __init__(self, **overrides: Any):
        defaults: Dict[str, Any] = {
            'max_beneficiaries': 60,
            'min_income': 0,
            'max_income': 400_000,
            'solo_parent_priority': False,
            'student_priority': False,
            'pwd_priority': True,
            'senior_citizen_priority': True,
            'priority_weights': {
                'low_income': 0.25,
                'solo_parent': 0.05,
                'student': 0.05,
                'pwd': 0.25,
                'senior_citizen': 0.40,
            },
            'description': 'Programs for senior citizens',
        }
        defaults.update(overrides)
        super().__init__(**defaults)


# ---------------------------------------------------------------------------
# Config Factory
# ---------------------------------------------------------------------------

class ConfigFactory:
    """Registry for looking up pre-defined configurations by name."""

    _registry: Dict[str, type] = {
        'balanced': BalancedConfig,
        'extreme_poverty': ExtremePovertyConfig,
        'youth_focus': YouthFocusConfig,
        'pwd_focus': PWDFocusConfig,
        'livelihood': LivelihoodConfig,
        'senior_citizen': SeniorCitizenConfig,
    }

    @classmethod
    def get_config(cls, config_type: str, **overrides: Any) -> RecommenderConfig:
        """Return a pre-defined config by name.

        Args:
            config_type: One of the registered names (e.g. ``'balanced'``).
            **overrides: Optional parameter overrides forwarded to the
                config constructor.

        Raises:
            KeyError: If *config_type* is not registered.
        """
        config_cls = cls._registry.get(config_type)
        if config_cls is None:
            available = ', '.join(sorted(cls._registry))
            raise KeyError(
                f'Unknown config type {config_type!r}. '
                f'Available: {available}'
            )
        return config_cls(**overrides)

    @classmethod
    def list_available(cls) -> List[str]:
        """Return sorted list of registered config-type names."""
        return sorted(cls._registry)

    @classmethod
    def list_available_detailed(cls) -> List[Dict[str, Any]]:
        """Return metadata for every registered config type."""
        out = []
        for name in sorted(cls._registry):
            cfg = cls._registry[name]()
            out.append({
                'name': name,
                'class': type(cfg).__name__,
                'description': cfg.description,
                'max_beneficiaries': cfg.max_beneficiaries,
                'max_income': cfg.max_income,
            })
        return out

    @classmethod
    def create_custom(cls, **kwargs: Any) -> RecommenderConfig:
        """Create a one-off ``RecommenderConfig`` with arbitrary params."""
        return RecommenderConfig(**kwargs)

    @classmethod
    def register(cls, name: str, config_cls: type) -> None:
        """Register a new config class under *name*."""
        if not (isinstance(config_cls, type) and issubclass(config_cls, RecommenderConfig)):
            raise TypeError('config_cls must be a RecommenderConfig subclass')
        cls._registry[name] = config_cls


# ---------------------------------------------------------------------------
# Config persistence (JSON files on disk)
# ---------------------------------------------------------------------------

class ConfigManager:
    """Load / save configuration snapshots to disk as versioned JSON files.

    Configs are stored under ``instance/recommender_configs/<config_type>/``.
    Each version is a separate JSON file named ``v<version>.json``.
    """

    def __init__(self, store_dir: str = _CONFIG_STORE_DIR):
        self.store_dir = store_dir

    # -- helpers ------------------------------------------------------------

    def _type_dir(self, config_type: str) -> str:
        return os.path.join(self.store_dir, config_type)

    def _version_path(self, config_type: str, version: str) -> str:
        # Sanitize version to prevent path traversal
        safe_version = ''.join(
            c for c in version if c.isalnum() or c in ('_', '-', '.')
        )
        if not safe_version:
            raise ValueError('version must contain at least one alphanumeric character')
        return os.path.join(self._type_dir(config_type), f'v{safe_version}.json')

    # -- public API ---------------------------------------------------------

    def save_config(
        self,
        config: RecommenderConfig,
        config_type: str,
        version: str,
    ) -> str:
        """Persist a config snapshot and return the file path."""
        path = self._version_path(config_type, version)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        payload = config.to_dict()
        payload['_meta'] = {
            'version': version,
            'config_type': config_type,
            'saved_at': datetime.now(timezone.utc).isoformat(),
        }

        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

        return path

    def load_config(
        self,
        config_type: str,
        version: str,
    ) -> RecommenderConfig:
        """Load a previously saved config snapshot.

        Uses ``ConfigFactory`` to resolve the right subclass when possible;
        falls back to the base ``RecommenderConfig``.
        """
        path = self._version_path(config_type, version)
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)

        data.pop('_meta', None)

        # Try to use the matching factory class
        try:
            cfg_cls = ConfigFactory._registry[config_type]
        except KeyError:
            cfg_cls = RecommenderConfig

        return cfg_cls.from_dict(data)

    def get_config_history(self, config_type: str) -> List[Dict[str, Any]]:
        """Return metadata for all saved versions of *config_type*."""
        type_dir = self._type_dir(config_type)
        if not os.path.isdir(type_dir):
            return []

        history: list[Dict[str, Any]] = []
        for fname in sorted(os.listdir(type_dir)):
            if not fname.endswith('.json'):
                continue
            path = os.path.join(type_dir, fname)
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                meta = data.get('_meta', {})
                history.append({
                    'version': meta.get('version', fname),
                    'saved_at': meta.get('saved_at'),
                    'file': path,
                    'config_type': config_type,
                })
            except (json.JSONDecodeError, OSError):
                continue

        return history

    def rollback_config(self, config_type: str, version: str) -> RecommenderConfig:
        """Convenience alias — loads the specified version."""
        return self.load_config(config_type, version)

    def get_latest_version(self, config_type: str) -> Optional[str]:
        """Return the most recently saved version string, or ``None``."""
        history = self.get_config_history(config_type)
        if not history:
            return None
        # Sort by saved_at descending
        history.sort(key=lambda h: h.get('saved_at', ''), reverse=True)
        return history[0]['version']
