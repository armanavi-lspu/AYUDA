"""
Tests for the recommender configuration framework.
"""
import json
import os
import shutil
import pytest

from app.config.recommender_configs import (
    RecommenderConfig,
    BalancedConfig,
    ExtremePovertyConfig,
    YouthFocusConfig,
    PWDFocusConfig,
    LivelihoodConfig,
    SeniorCitizenConfig,
    ConfigFactory,
    ConfigManager,
)


# ---------------------------------------------------------------------------
# RecommenderConfig base class
# ---------------------------------------------------------------------------

class TestRecommenderConfig:

    def test_default_construction(self):
        cfg = RecommenderConfig()
        assert cfg.max_beneficiaries == 50
        assert cfg.min_income == 0
        assert cfg.max_income == 10_000_000
        assert cfg.priority_barangays is None
        assert cfg.solo_parent_priority is False
        assert cfg.priority_weights is None

    def test_custom_construction(self):
        cfg = RecommenderConfig(
            max_beneficiaries=100,
            min_income=5000,
            max_income=300_000,
            solo_parent_priority=True,
            pwd_priority=True,
        )
        assert cfg.max_beneficiaries == 100
        assert cfg.min_income == 5000
        assert cfg.max_income == 300_000
        assert cfg.solo_parent_priority is True
        assert cfg.pwd_priority is True

    def test_to_dict_roundtrip(self):
        cfg = RecommenderConfig(max_beneficiaries=30, student_priority=True)
        d = cfg.to_dict()
        cfg2 = RecommenderConfig.from_dict(d)
        assert cfg == cfg2

    def test_to_kwargs(self):
        cfg = RecommenderConfig(
            max_beneficiaries=20,
            min_income=1000,
            max_income=50000,
            solo_parent_priority=True,
            priority_barangays=['Poblacion', 'San Jose'],
        )
        kw = cfg.to_kwargs()
        assert kw['max_beneficiaries'] == 20
        assert kw['solo_parent_priority'] is True
        assert kw['priority_barangays'] == ['Poblacion', 'San Jose']
        assert 'priority_weights' not in kw
        assert 'description' not in kw

    def test_copy_with_overrides(self):
        cfg = RecommenderConfig(max_beneficiaries=50, solo_parent_priority=True)
        cfg2 = cfg.copy(max_beneficiaries=100)
        assert cfg2.max_beneficiaries == 100
        assert cfg2.solo_parent_priority is True
        assert cfg.max_beneficiaries == 50  # original unchanged

    def test_repr(self):
        cfg = RecommenderConfig(max_beneficiaries=10)
        r = repr(cfg)
        assert 'RecommenderConfig(' in r
        assert 'max_beneficiaries=10' in r

    def test_equality(self):
        a = RecommenderConfig(max_beneficiaries=50, pwd_priority=True)
        b = RecommenderConfig(max_beneficiaries=50, pwd_priority=True)
        assert a == b

    def test_inequality(self):
        a = RecommenderConfig(max_beneficiaries=50)
        b = RecommenderConfig(max_beneficiaries=100)
        assert a != b


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:

    def test_negative_max_beneficiaries(self):
        with pytest.raises(ValueError, match='positive integer'):
            RecommenderConfig(max_beneficiaries=-1)

    def test_zero_max_beneficiaries(self):
        with pytest.raises(ValueError, match='positive integer'):
            RecommenderConfig(max_beneficiaries=0)

    def test_over_500_max_beneficiaries(self):
        with pytest.raises(ValueError, match='must not exceed 500'):
            RecommenderConfig(max_beneficiaries=501)

    def test_negative_min_income(self):
        with pytest.raises(ValueError, match='min_income must be >= 0'):
            RecommenderConfig(min_income=-100)

    def test_max_income_exceeds_ceiling(self):
        with pytest.raises(ValueError, match='must not exceed'):
            RecommenderConfig(max_income=20_000_000)

    def test_min_greater_than_max_income(self):
        with pytest.raises(ValueError, match='min_income must be <= max_income'):
            RecommenderConfig(min_income=500_000, max_income=100_000)

    def test_invalid_priority_weight_key(self):
        with pytest.raises(ValueError, match='Unknown priority_weights keys'):
            RecommenderConfig(priority_weights={'bad_key': 0.5})

    def test_negative_priority_weight_value(self):
        with pytest.raises(ValueError, match='non-negative number'):
            RecommenderConfig(priority_weights={'low_income': -0.1})

    def test_empty_barangay_string(self):
        with pytest.raises(ValueError, match='non-empty strings'):
            RecommenderConfig(priority_barangays=['Poblacion', ''])

    def test_valid_priority_weights(self):
        cfg = RecommenderConfig(priority_weights={
            'low_income': 0.3, 'solo_parent': 0.2, 'student': 0.15,
            'pwd': 0.2, 'senior_citizen': 0.15,
        })
        assert sum(cfg.priority_weights.values()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Pre-defined configurations
# ---------------------------------------------------------------------------

class TestPresetConfigs:

    def test_balanced_defaults(self):
        cfg = BalancedConfig()
        assert cfg.max_beneficiaries == 75
        assert cfg.max_income == 400_000
        assert cfg.solo_parent_priority is True
        assert cfg.student_priority is True
        assert cfg.pwd_priority is True
        assert cfg.senior_citizen_priority is True

    def test_extreme_poverty_defaults(self):
        cfg = ExtremePovertyConfig()
        assert cfg.max_beneficiaries == 120
        assert cfg.max_income == 200_000
        assert cfg.pwd_priority is True
        assert cfg.student_priority is False

    def test_youth_focus_defaults(self):
        cfg = YouthFocusConfig()
        assert cfg.max_beneficiaries == 50
        assert cfg.max_income == 600_000
        assert cfg.student_priority is True
        assert cfg.priority_weights['student'] == 0.40

    def test_pwd_focus_defaults(self):
        cfg = PWDFocusConfig()
        assert cfg.max_beneficiaries == 40
        assert cfg.pwd_priority is True
        assert cfg.priority_weights['pwd'] == 0.45

    def test_livelihood_defaults(self):
        cfg = LivelihoodConfig()
        assert cfg.max_beneficiaries == 100
        assert cfg.solo_parent_priority is True

    def test_senior_citizen_defaults(self):
        cfg = SeniorCitizenConfig()
        assert cfg.max_beneficiaries == 60
        assert cfg.senior_citizen_priority is True
        assert cfg.priority_weights['senior_citizen'] == 0.40

    def test_preset_override(self):
        cfg = BalancedConfig(max_beneficiaries=200, max_income=300_000)
        assert cfg.max_beneficiaries == 200
        assert cfg.max_income == 300_000
        assert cfg.solo_parent_priority is True  # default preserved

    def test_all_presets_validate(self):
        """Every pre-defined config must pass validation without error."""
        for name in ConfigFactory.list_available():
            cfg = ConfigFactory.get_config(name)
            cfg.validate()  # should not raise

    def test_all_presets_weights_sum_to_one(self):
        for name in ConfigFactory.list_available():
            cfg = ConfigFactory.get_config(name)
            if cfg.priority_weights:
                total = sum(cfg.priority_weights.values())
                assert total == pytest.approx(1.0, abs=0.01), (
                    f'{name} weights sum to {total}'
                )


# ---------------------------------------------------------------------------
# ConfigFactory
# ---------------------------------------------------------------------------

class TestConfigFactory:

    def test_list_available(self):
        available = ConfigFactory.list_available()
        assert 'balanced' in available
        assert 'extreme_poverty' in available
        assert 'youth_focus' in available

    def test_list_available_detailed(self):
        details = ConfigFactory.list_available_detailed()
        assert len(details) >= 6
        assert all('name' in d and 'description' in d for d in details)

    def test_get_config(self):
        cfg = ConfigFactory.get_config('balanced')
        assert isinstance(cfg, BalancedConfig)

    def test_get_config_unknown(self):
        with pytest.raises(KeyError, match='Unknown config type'):
            ConfigFactory.get_config('nonexistent')

    def test_get_config_with_override(self):
        cfg = ConfigFactory.get_config('balanced', max_beneficiaries=200)
        assert cfg.max_beneficiaries == 200

    def test_create_custom(self):
        cfg = ConfigFactory.create_custom(
            max_beneficiaries=25,
            pwd_priority=True,
            description='Custom one-off',
        )
        assert isinstance(cfg, RecommenderConfig)
        assert cfg.max_beneficiaries == 25

    def test_register_custom_class(self):
        class TestConfig(RecommenderConfig):
            def __init__(self, **kw):
                defaults = {'max_beneficiaries': 10, 'description': 'test'}
                defaults.update(kw)
                super().__init__(**defaults)

        ConfigFactory.register('_test_custom', TestConfig)
        assert '_test_custom' in ConfigFactory.list_available()
        cfg = ConfigFactory.get_config('_test_custom')
        assert cfg.max_beneficiaries == 10

        # cleanup
        ConfigFactory._registry.pop('_test_custom', None)

    def test_register_invalid_class(self):
        with pytest.raises(TypeError):
            ConfigFactory.register('bad', dict)


# ---------------------------------------------------------------------------
# ConfigManager (persistence)
# ---------------------------------------------------------------------------

class TestConfigManager:

    @pytest.fixture(autouse=True)
    def tmp_store(self, tmp_path):
        self.store_dir = str(tmp_path / 'configs')
        self.manager = ConfigManager(store_dir=self.store_dir)

    def test_save_and_load(self):
        cfg = BalancedConfig()
        self.manager.save_config(cfg, 'balanced', '1.0')
        loaded = self.manager.load_config('balanced', '1.0')
        assert loaded.max_beneficiaries == cfg.max_beneficiaries
        assert loaded.max_income == cfg.max_income

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            self.manager.load_config('balanced', '99.0')

    def test_get_config_history(self):
        cfg = BalancedConfig()
        self.manager.save_config(cfg, 'balanced', '1.0')
        self.manager.save_config(cfg.copy(max_beneficiaries=100), 'balanced', '2.0')

        history = self.manager.get_config_history('balanced')
        assert len(history) == 2
        versions = {h['version'] for h in history}
        assert versions == {'1.0', '2.0'}

    def test_get_config_history_empty(self):
        assert self.manager.get_config_history('nonexistent') == []

    def test_rollback_config(self):
        v1 = BalancedConfig(max_beneficiaries=75)
        v2 = BalancedConfig(max_beneficiaries=200)
        self.manager.save_config(v1, 'balanced', '1.0')
        self.manager.save_config(v2, 'balanced', '2.0')

        rolled_back = self.manager.rollback_config('balanced', '1.0')
        assert rolled_back.max_beneficiaries == 75

    def test_get_latest_version(self):
        cfg = ExtremePovertyConfig()
        self.manager.save_config(cfg, 'extreme_poverty', '1.0')
        self.manager.save_config(cfg, 'extreme_poverty', '2.0')
        assert self.manager.get_latest_version('extreme_poverty') is not None

    def test_get_latest_version_none(self):
        assert self.manager.get_latest_version('nonexistent') is None

    def test_saved_file_contains_meta(self):
        cfg = YouthFocusConfig()
        path = self.manager.save_config(cfg, 'youth_focus', '1.0')
        with open(path, encoding='utf-8') as f:
            payload = json.load(f)
        assert '_meta' in payload
        assert payload['_meta']['version'] == '1.0'
        assert payload['_meta']['config_type'] == 'youth_focus'


# ---------------------------------------------------------------------------
# Integration: config -> get_recommendations kwargs
# ---------------------------------------------------------------------------

class TestConfigRecommenderIntegration:
    """Ensure configs produce valid kwargs for get_recommendations."""

    @pytest.fixture
    def sample_beneficiaries(self):
        return [
            {
                'user_id': 1, 'first_name': 'Juan', 'last_name': 'Dela Cruz',
                'email': 'juan@test.com', 'age': 35, 'barangay': 'Poblacion',
                'family_annual_income': 50000, 'is_solo_parent': True,
                'is_student': False, 'is_pwd': True,
                'is_currently_employed': False, 'occupation': 'None',
            },
            {
                'user_id': 2, 'first_name': 'Maria', 'last_name': 'Santos',
                'email': 'maria@test.com', 'age': 28, 'barangay': 'Bagong Silang',
                'family_annual_income': 120000, 'is_solo_parent': False,
                'is_student': True, 'is_pwd': False,
                'is_currently_employed': True, 'occupation': 'Teacher',
            },
            {
                'user_id': 3, 'first_name': 'Pedro', 'last_name': 'Garcia',
                'email': 'pedro@test.com', 'age': 65, 'barangay': 'Poblacion',
                'family_annual_income': 30000, 'is_solo_parent': False,
                'is_student': False, 'is_pwd': False,
                'is_currently_employed': False, 'occupation': 'Farmer',
            },
            {
                'user_id': 4, 'first_name': 'Ana', 'last_name': 'Lopez',
                'email': 'ana@test.com', 'age': 22, 'barangay': 'San Jose',
                'family_annual_income': 80000, 'is_solo_parent': False,
                'is_student': True, 'is_pwd': True,
                'is_currently_employed': False, 'occupation': 'Student',
            },
        ]

    def test_balanced_config_produces_results(self, sample_beneficiaries):
        from app.recommender import get_recommendations
        cfg = BalancedConfig()
        results = get_recommendations(sample_beneficiaries, **cfg.to_kwargs())
        assert len(results) > 0
        assert all('score' in r for r in results)

    def test_extreme_poverty_filters_income(self, sample_beneficiaries):
        from app.recommender import get_recommendations
        cfg = ExtremePovertyConfig()
        results = get_recommendations(sample_beneficiaries, **cfg.to_kwargs())
        for r in results:
            assert r['family_annual_income'] <= cfg.max_income

    def test_youth_focus_prioritises_students(self, sample_beneficiaries):
        from app.recommender import get_recommendations
        cfg = YouthFocusConfig()
        results = get_recommendations(sample_beneficiaries, **cfg.to_kwargs())
        students = [r for r in results if r['is_student']]
        non_students = [r for r in results if not r['is_student']]
        if students and non_students:
            assert students[0]['score'] >= non_students[-1]['score']

    def test_pwd_focus_prioritises_pwd(self, sample_beneficiaries):
        from app.recommender import get_recommendations
        cfg = PWDFocusConfig()
        results = get_recommendations(sample_beneficiaries, **cfg.to_kwargs())
        pwd = [r for r in results if r['is_pwd']]
        assert len(pwd) > 0

    def test_senior_citizen_config(self, sample_beneficiaries):
        from app.recommender import get_recommendations
        cfg = SeniorCitizenConfig()
        results = get_recommendations(sample_beneficiaries, **cfg.to_kwargs())
        assert len(results) > 0
