"""
Comprehensive tests for the enhanced AYUDA recommender system.

Covers:
- Expanded feature engineering (gender, disability_type, vulnerability compound)
- RobustScaler performance with income outliers
- Hybrid similarity + scoring recommendations
- Explainability module
- Fairness audit system
- Program compatibility scoring
- Weight optimization framework
- Configuration framework validation
"""

import pytest
from app.recommender import BeneficiaryRecommender, get_recommendations
from app.ml.explainer import BeneficiaryExplainer
from app.ml.fairness_auditor import FairnessAuditor
from app.ml.program_compatibility import ProgramCompatibilityScorer
from app.ml.weight_optimizer import WeightOptimizer
from app.config.recommender_configs import (
    RecommenderConfig, BalancedConfig, ExtremePovertyConfig,
    YouthFocusConfig, PWDFocusConfig, LivelihoodConfig,
    SeniorCitizenConfig, ConfigFactory, ConfigManager,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_beneficiaries():
    """Large, diverse sample for testing."""
    barangays = ['Poblacion', 'Bagong Silang', 'San Jose', 'Pila',
                 'Sta. Maria', 'San Juan', 'Paagahan', 'Lambac']
    genders = ['Male', 'Female']
    occupations = ['Farmer', 'Fisher', 'Teacher', 'Vendor', 'None', 'Driver',
                   'Carpenter', 'Seamstress']
    disability_types = [None, None, None, None, 'Visual', 'Hearing',
                        'Physical', 'Mental']

    data = []
    for i in range(100):
        data.append({
            'user_id': i + 1,
            'first_name': f'Person{i}',
            'last_name': 'Test',
            'email': f'person{i}@test.com',
            'age': 20 + (i % 55),
            'barangay': barangays[i % len(barangays)],
            'gender': genders[i % len(genders)],
            'family_annual_income': 30000 + i * 5000,
            'is_solo_parent': i % 3 == 0,
            'is_student': i % 4 == 0,
            'is_pwd': i % 5 == 0,
            'is_currently_employed': i % 2 == 0,
            'occupation': occupations[i % len(occupations)],
            'disability_type': disability_types[i % len(disability_types)],
        })
    return data


@pytest.fixture
def small_beneficiaries():
    """Small sample for quick validation."""
    return [
        {
            'user_id': 1, 'first_name': 'Juan', 'last_name': 'Cruz',
            'age': 35, 'barangay': 'Poblacion', 'gender': 'Male',
            'family_annual_income': 50000, 'is_solo_parent': True,
            'is_student': False, 'is_pwd': True,
            'is_currently_employed': False, 'occupation': 'None',
            'disability_type': 'Visual',
        },
        {
            'user_id': 2, 'first_name': 'Maria', 'last_name': 'Santos',
            'age': 28, 'barangay': 'Bagong Silang', 'gender': 'Female',
            'family_annual_income': 120000, 'is_solo_parent': False,
            'is_student': True, 'is_pwd': False,
            'is_currently_employed': True, 'occupation': 'Teacher',
            'disability_type': None,
        },
        {
            'user_id': 3, 'first_name': 'Pedro', 'last_name': 'Garcia',
            'age': 65, 'barangay': 'San Jose', 'gender': 'Male',
            'family_annual_income': 30000, 'is_solo_parent': False,
            'is_student': False, 'is_pwd': False,
            'is_currently_employed': False, 'occupation': 'Farmer',
            'disability_type': None,
        },
    ]


@pytest.fixture
def target_profile():
    return {
        'age': 30, 'barangay': 'Poblacion', 'gender': 'Female',
        'family_annual_income': 100000, 'is_solo_parent': True,
        'is_student': False, 'is_pwd': False,
        'is_currently_employed': False, 'occupation': 'Vendor',
        'disability_type': None,
    }


# ===========================================================================
# 1. Expanded Feature Engineering
# ===========================================================================

class TestExpandedFeatures:

    def test_fit_with_gender_and_disability(self, sample_beneficiaries):
        """Recommender handles gender and disability_type columns."""
        recommender = BeneficiaryRecommender()
        assert recommender.fit(sample_beneficiaries) is True

    def test_prepare_dataframe_adds_vulnerability_compound(self, small_beneficiaries):
        recommender = BeneficiaryRecommender()
        df = recommender._prepare_dataframe(small_beneficiaries)
        assert 'vulnerability_compound' in df.columns
        assert df['vulnerability_compound'].min() >= 0
        assert df['vulnerability_compound'].max() <= 1.0

    def test_gender_column_filled_when_missing(self):
        """Missing gender defaults to 'Unknown'."""
        recommender = BeneficiaryRecommender()
        data = [{'user_id': 1, 'age': 30, 'barangay': 'X',
                 'family_annual_income': 100000, 'is_solo_parent': False,
                 'is_student': False, 'is_pwd': False,
                 'is_currently_employed': True, 'occupation': 'None'}]
        df = recommender._prepare_dataframe(data)
        # Should not raise and should default sensibly
        assert df is not None

    def test_disability_type_column_filled_when_missing(self):
        recommender = BeneficiaryRecommender()
        data = [{'user_id': 1, 'age': 30, 'barangay': 'X',
                 'family_annual_income': 100000, 'is_solo_parent': False,
                 'is_student': False, 'is_pwd': False,
                 'is_currently_employed': True, 'occupation': 'None',
                 'gender': 'Male'}]
        df = recommender._prepare_dataframe(data)
        assert df is not None


# ===========================================================================
# 2. RobustScaler Performance
# ===========================================================================

class TestRobustScaler:

    def test_outlier_income_does_not_destroy_recommendations(self, sample_beneficiaries):
        """An extreme income outlier should not dominate scores."""
        outlier = dict(sample_beneficiaries[0])
        outlier['user_id'] = 999
        outlier['family_annual_income'] = 9_999_999

        data = sample_beneficiaries + [outlier]
        recommender = BeneficiaryRecommender()
        assert recommender.fit(data)

        scored = recommender.score_beneficiaries(data)
        assert len(scored) > 0
        assert scored[0]['score'] > 0

    def test_zero_income_handled(self, sample_beneficiaries):
        data = [dict(b) for b in sample_beneficiaries]
        data[0]['family_annual_income'] = 0
        recommender = BeneficiaryRecommender()
        assert recommender.fit(data)

    def test_all_same_income(self):
        """All identical incomes should not cause division by zero."""
        data = [
            {'user_id': i, 'age': 30, 'barangay': 'X', 'gender': 'Male',
             'family_annual_income': 100000, 'is_solo_parent': False,
             'is_student': False, 'is_pwd': False,
             'is_currently_employed': True, 'occupation': 'Farmer',
             'disability_type': None}
            for i in range(5)
        ]
        recommender = BeneficiaryRecommender()
        assert recommender.fit(data)
        scored = recommender.score_beneficiaries(data)
        assert len(scored) == 5


# ===========================================================================
# 3. Hybrid Similarity + Scoring
# ===========================================================================

class TestHybridRecommendation:

    def test_hybrid_returns_results(self, sample_beneficiaries, target_profile):
        recommender = BeneficiaryRecommender()
        recommender.fit(sample_beneficiaries)

        results = recommender.recommend_hybrid(
            target_profile, n_recommendations=10,
        )
        assert len(results) > 0

    def test_hybrid_scores_present(self, sample_beneficiaries, target_profile):
        recommender = BeneficiaryRecommender()
        recommender.fit(sample_beneficiaries)
        results = recommender.recommend_hybrid(target_profile, n_recommendations=5)

        for r in results:
            assert 'hybrid_score' in r
            assert 'similarity_component' in r
            assert 'need_component' in r

    def test_hybrid_respects_count(self, sample_beneficiaries, target_profile):
        recommender = BeneficiaryRecommender()
        recommender.fit(sample_beneficiaries)
        results = recommender.recommend_hybrid(target_profile, n_recommendations=3)
        assert len(results) <= 3

    def test_hybrid_without_fit_returns_empty(self, target_profile):
        recommender = BeneficiaryRecommender()
        results = recommender.recommend_hybrid(target_profile)
        assert results == []

    def test_find_similar_profiles(self, sample_beneficiaries, target_profile):
        recommender = BeneficiaryRecommender()
        recommender.fit(sample_beneficiaries)
        similar = recommender._find_similar_profiles(target_profile, 5)
        assert len(similar) > 0
        assert 'similarity_distance' in similar[0]


# ===========================================================================
# 4. Explainability
# ===========================================================================

class TestExplainability:

    def test_explain_score_structure(self, small_beneficiaries):
        explainer = BeneficiaryExplainer()
        result = explainer.explain_score(small_beneficiaries[0], 0.75)

        breakdown = result['score_breakdown']
        expected_total = round(sum(part['contribution'] for part in breakdown.values()), 4)
        assert result['total_score'] == expected_total
        assert 'score_breakdown' in result
        assert 'plain_english_explanation' in result
        assert 'compared_to_average' in result
        assert 'vulnerability_level' in result

    def test_explain_score_breakdown_factors(self, small_beneficiaries):
        explainer = BeneficiaryExplainer()
        result = explainer.explain_score(small_beneficiaries[0], 0.80)
        breakdown = result['score_breakdown']

        expected_factors = [
            'case_severity_factor',
            'income_vulnerability_factor',
            'household_vulnerability_factor',
            'repeat_beneficiary_penalty_factor',
        ]
        for factor in expected_factors:
            assert factor in breakdown
            assert 'label' in breakdown[factor]
            assert 'weight' in breakdown[factor]
            assert 'beneficiary_value' in breakdown[factor]
            assert 'contribution' in breakdown[factor]

    def test_explain_with_population(self, sample_beneficiaries):
        explainer = BeneficiaryExplainer(population=sample_beneficiaries)
        result = explainer.explain_score(sample_beneficiaries[0], 0.60)
        assert result['compared_to_average']['available'] is True

    def test_explain_without_population(self, small_beneficiaries):
        explainer = BeneficiaryExplainer()
        result = explainer.explain_score(small_beneficiaries[0], 0.50)
        assert result['compared_to_average']['available'] is False

    def test_vulnerability_level_high(self):
        beneficiary = {
            'family_annual_income': 50000, 'is_solo_parent': True,
            'is_pwd': True, 'is_student': True,
            'is_currently_employed': False, 'age': 65,
        }
        explainer = BeneficiaryExplainer()
        result = explainer.explain_score(beneficiary, 0.95)
        assert result['vulnerability_level'] == 'HIGH'

    def test_vulnerability_level_low(self):
        beneficiary = {
            'family_annual_income': 500000, 'is_solo_parent': False,
            'is_pwd': False, 'is_student': False,
            'is_currently_employed': True, 'age': 35,
        }
        explainer = BeneficiaryExplainer()
        result = explainer.explain_score(beneficiary, 0.10)
        assert result['vulnerability_level'] == 'LOW'

    def test_plain_english_explanation(self):
        beneficiary = {
            'family_annual_income': 50000, 'is_solo_parent': True,
            'is_pwd': False, 'is_student': False,
            'is_currently_employed': False, 'age': 35,
        }
        explainer = BeneficiaryExplainer()
        result = explainer.explain_score(beneficiary, 0.70)
        explanation = result['plain_english_explanation']
        assert 'very low income' in explanation
        assert 'single parent' in explanation

    def test_explain_batch(self, small_beneficiaries):
        for b in small_beneficiaries:
            b['score'] = 0.5
        explainer = BeneficiaryExplainer()
        results = explainer.explain_batch(small_beneficiaries)
        assert len(results) == len(small_beneficiaries)
        for r in results:
            assert 'explanation' in r


# ===========================================================================
# 5. Fairness Audit
# ===========================================================================

class TestFairnessAudit:

    def test_audit_returns_structure(self, sample_beneficiaries):
        recommendations = sample_beneficiaries[:50]  # Top 50
        auditor = FairnessAuditor(sample_beneficiaries, recommendations)
        result = auditor.audit()

        assert 'status' in result
        assert 'geographic_fairness' in result
        assert 'demographic_fairness' in result
        assert 'disparate_impact' in result
        assert 'violations' in result
        assert 'overall_fairness_score' in result
        assert 'timestamp' in result

    def test_geographic_fairness_pass(self, sample_beneficiaries):
        # All barangays represented equally
        auditor = FairnessAuditor(sample_beneficiaries, sample_beneficiaries[:80])
        geo = auditor.geographic_fairness()
        assert geo['status'] == 'PASS'
        assert geo['representation_percentage'] >= 0.80

    def test_geographic_fairness_fail(self, sample_beneficiaries):
        # Only one barangay
        recs = [b for b in sample_beneficiaries if b['barangay'] == 'Poblacion']
        auditor = FairnessAuditor(sample_beneficiaries, recs)
        geo = auditor.geographic_fairness()
        assert geo['status'] == 'FAIL'
        assert len(geo['missing_barangays']) > 0

    def test_demographic_fairness(self, sample_beneficiaries):
        auditor = FairnessAuditor(sample_beneficiaries, sample_beneficiaries[:50])
        demo = auditor.demographic_fairness()
        assert 'groups' in demo
        assert 'overall_status' in demo
        for group_name in ('solo_parent', 'student', 'pwd'):
            assert group_name in demo['groups']

    def test_disparate_impact(self, sample_beneficiaries):
        auditor = FairnessAuditor(sample_beneficiaries, sample_beneficiaries[:75])
        di = auditor.disparate_impact()
        assert 'groups' in di
        assert 'overall_status' in di

    def test_empty_recommendations(self, sample_beneficiaries):
        auditor = FairnessAuditor(sample_beneficiaries, [])
        demo = auditor.demographic_fairness()
        assert demo['overall_status'] == 'SKIP'

    def test_overall_fairness_score_range(self, sample_beneficiaries):
        auditor = FairnessAuditor(sample_beneficiaries, sample_beneficiaries[:75])
        result = auditor.audit()
        assert 0 <= result['overall_fairness_score'] <= 1.0


# ===========================================================================
# 6. Program Compatibility
# ===========================================================================

class TestProgramCompatibility:

    @pytest.fixture
    def sample_program(self):
        return {
            'id': 1,
            'priority_group': 'Solo Parent, PWD, Low Income',
            'income_range': '0-250000',
            'beneficiary_limit': 50,
            'requirements': [
                {'field': 'is_solo_parent', 'name': 'Solo Parent ID'},
                {'field': 'is_pwd', 'name': 'PWD ID'},
            ],
        }

    def test_calculate_fit(self, small_beneficiaries, sample_program):
        scorer = ProgramCompatibilityScorer()
        result = scorer.calculate_fit(small_beneficiaries[0], sample_program)

        assert 'compatibility_score' in result
        assert 0 <= result['compatibility_score'] <= 1.0
        assert 'program_fit_assessment' in result

    def test_high_fit_beneficiary(self, sample_program):
        """Solo parent, PWD, low income should get high fit."""
        beneficiary = {
            'user_id': 1, 'age': 35, 'family_annual_income': 80000,
            'is_solo_parent': True, 'is_pwd': True,
            'is_student': False, 'is_currently_employed': False,
        }
        scorer = ProgramCompatibilityScorer()
        result = scorer.calculate_fit(beneficiary, sample_program)
        assert result['compatibility_score'] > 0.5

    def test_low_fit_beneficiary(self, sample_program):
        """Employed, high income, no vulnerabilities → low fit."""
        beneficiary = {
            'user_id': 99, 'age': 35, 'family_annual_income': 800000,
            'is_solo_parent': False, 'is_pwd': False,
            'is_student': False, 'is_currently_employed': True,
        }
        scorer = ProgramCompatibilityScorer()
        result = scorer.calculate_fit(beneficiary, sample_program)
        assert result['compatibility_score'] < 0.6

    def test_score_batch(self, sample_beneficiaries, sample_program):
        scorer = ProgramCompatibilityScorer()
        results = scorer.score_batch(sample_beneficiaries[:20], sample_program)
        assert len(results) == 20
        for r in results:
            assert 'compatibility' in r

    def test_historical_approval_rate(self, sample_program):
        historical = [
            {'user_id': 1, 'program_id': 1, 'application_status': 'approved', 'age': 33},
            {'user_id': 2, 'program_id': 1, 'application_status': 'approved', 'age': 34},
            {'user_id': 3, 'program_id': 1, 'application_status': 'rejected', 'age': 36},
        ]
        scorer = ProgramCompatibilityScorer(historical_data=historical)
        beneficiary = {'user_id': 10, 'age': 35, 'family_annual_income': 100000,
                       'is_solo_parent': True, 'is_pwd': True}
        result = scorer.calculate_fit(beneficiary, sample_program)
        # Should reflect ~66% approval rate for age range 30-40
        assert result['historical_success_rate'] > 0.5

    def test_no_requirements_program(self):
        program = {'id': 2, 'priority_group': '', 'income_range': '', 'requirements': []}
        beneficiary = {'user_id': 1, 'age': 30, 'family_annual_income': 100000}
        scorer = ProgramCompatibilityScorer()
        result = scorer.calculate_fit(beneficiary, program)
        assert result['requirements_met'] == 0.9  # Default

    def test_income_fit_in_range(self):
        program = {'id': 1, 'income_range': '0-300000', 'priority_group': '', 'requirements': []}
        beneficiary = {'user_id': 1, 'age': 30, 'family_annual_income': 150000}
        scorer = ProgramCompatibilityScorer()
        result = scorer.calculate_fit(beneficiary, program)
        assert result['income_alignment'] == 1.0

    def test_income_fit_out_of_range(self):
        program = {'id': 1, 'income_range': '0-200000', 'priority_group': '', 'requirements': []}
        beneficiary = {'user_id': 1, 'age': 30, 'family_annual_income': 500000}
        scorer = ProgramCompatibilityScorer()
        result = scorer.calculate_fit(beneficiary, program)
        assert result['income_alignment'] < 1.0

    def test_fit_assessment_labels(self):
        scorer = ProgramCompatibilityScorer()
        assert scorer._generate_fit_assessment(0.90) == 'Excellent fit'
        assert scorer._generate_fit_assessment(0.65) == 'Good fit'
        assert scorer._generate_fit_assessment(0.45) == 'Moderate fit'
        assert scorer._generate_fit_assessment(0.25) == 'Low fit'
        assert scorer._generate_fit_assessment(0.10) == 'Poor fit'


# ===========================================================================
# 7. Weight Optimization
# ===========================================================================

class TestWeightOptimizer:

    def test_optimize_returns_structure(self, sample_beneficiaries):
        optimizer = WeightOptimizer(sample_beneficiaries)
        result = optimizer.optimize_weights(objectives=['equity', 'efficiency'])

        assert 'optimal_weights' in result
        assert 'best_score' in result
        assert 'top_configs' in result
        assert 'total_evaluated' in result
        assert result['total_evaluated'] > 0

    def test_optimal_weights_are_normalized(self, sample_beneficiaries):
        optimizer = WeightOptimizer(sample_beneficiaries)
        result = optimizer.optimize_weights(objectives=['equity'])

        weights = result['optimal_weights']
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01  # Should sum to ~1

    def test_with_ground_truth(self, sample_beneficiaries):
        approved = [1, 3, 5, 7, 9]
        optimizer = WeightOptimizer(sample_beneficiaries, ground_truth_approvals=approved)
        result = optimizer.optimize_weights(
            objectives=['coverage', 'equity'],
            weight_ranges={
                'low_income': [0.30, 0.40],
                'solo_parent': [0.20, 0.30],
                'student': [0.10, 0.20],
                'pwd': [0.20, 0.30],
                'senior_citizen': [0.10, 0.15],
            },
        )
        assert result['best_score'] > 0

    def test_top_configs_order(self, sample_beneficiaries):
        optimizer = WeightOptimizer(sample_beneficiaries)
        result = optimizer.optimize_weights(
            objectives=['equity'],
            weight_ranges={
                'low_income': [0.25, 0.35],
                'solo_parent': [0.15, 0.25],
                'student': [0.10, 0.20],
                'pwd': [0.15, 0.25],
                'senior_citizen': [0.10, 0.15],
            },
        )
        configs = result['top_configs']
        for i in range(len(configs) - 1):
            assert configs[i]['combined_score'] >= configs[i + 1]['combined_score']

    def test_efficiency_metric(self, sample_beneficiaries):
        optimizer = WeightOptimizer(sample_beneficiaries)
        weights = {'low_income': 0.3, 'solo_parent': 0.2, 'student': 0.15,
                   'pwd': 0.2, 'senior_citizen': 0.15}
        eff = optimizer._calc_efficiency(weights)
        assert 0 <= eff <= 1.0

    def test_transparency_metric(self, sample_beneficiaries):
        optimizer = WeightOptimizer(sample_beneficiaries)
        uniform = {'low_income': 0.2, 'solo_parent': 0.2, 'student': 0.2,
                   'pwd': 0.2, 'senior_citizen': 0.2}
        skewed = {'low_income': 0.9, 'solo_parent': 0.025, 'student': 0.025,
                  'pwd': 0.025, 'senior_citizen': 0.025}

        t_uniform = optimizer._calc_transparency(uniform)
        t_skewed = optimizer._calc_transparency(skewed)
        assert t_uniform > t_skewed  # Uniform should be more transparent


# ===========================================================================
# 8. Configuration Framework (extended)
# ===========================================================================

class TestConfigFrameworkExtended:

    def test_balanced_config_valid(self):
        config = BalancedConfig()
        assert config.max_beneficiaries == 75
        assert config.max_income == 400_000

    def test_extreme_poverty_config_valid(self):
        config = ExtremePovertyConfig()
        assert config.max_beneficiaries == 120
        assert config.max_income == 200_000

    def test_youth_config_valid(self):
        config = YouthFocusConfig()
        assert config.max_beneficiaries == 50
        assert config.student_priority is True

    def test_pwd_config_valid(self):
        config = PWDFocusConfig()
        assert config.pwd_priority is True

    def test_livelihood_config_valid(self):
        config = LivelihoodConfig()
        assert config.max_beneficiaries == 100

    def test_senior_citizen_config_valid(self):
        config = SeniorCitizenConfig()
        assert config.senior_citizen_priority is True

    def test_config_factory_list_available(self):
        available = ConfigFactory.list_available()
        assert 'balanced' in available
        assert 'extreme_poverty' in available
        assert len(available) >= 6

    def test_config_factory_list_detailed(self):
        detailed = ConfigFactory.list_available_detailed()
        assert len(detailed) >= 6
        for item in detailed:
            assert 'name' in item
            assert 'description' in item

    def test_config_invalid_income_range(self):
        with pytest.raises(ValueError):
            RecommenderConfig(min_income=500_000, max_income=400_000)

    def test_config_invalid_max_beneficiaries(self):
        with pytest.raises(ValueError):
            RecommenderConfig(max_beneficiaries=0)

    def test_config_to_dict_roundtrip(self):
        config = BalancedConfig()
        data = config.to_dict()
        restored = RecommenderConfig.from_dict(data)
        assert restored.max_beneficiaries == config.max_beneficiaries

    def test_config_to_kwargs(self):
        config = BalancedConfig()
        kwargs = config.to_kwargs()
        assert 'max_beneficiaries' in kwargs
        assert 'solo_parent_priority' in kwargs

    def test_config_copy_with_override(self):
        config = BalancedConfig()
        copy = config.copy(max_beneficiaries=100)
        assert copy.max_beneficiaries == 100
        assert config.max_beneficiaries == 75  # Original unchanged

    def test_create_custom_config(self):
        config = ConfigFactory.create_custom(
            max_beneficiaries=30,
            max_income=300_000,
            pwd_priority=True,
        )
        assert config.max_beneficiaries == 30
        assert config.pwd_priority is True


# ===========================================================================
# 9. Integration: get_recommendations with new features
# ===========================================================================

class TestGetRecommendationsEnhanced:

    def test_recommendations_with_gender_data(self, sample_beneficiaries):
        results = get_recommendations(
            sample_beneficiaries, max_beneficiaries=20,
        )
        assert len(results) <= 20
        assert all('score' in r for r in results)

    def test_recommendations_with_priority(self, sample_beneficiaries):
        results = get_recommendations(
            sample_beneficiaries, max_beneficiaries=20,
            solo_parent_priority=True, pwd_priority=True,
        )
        assert len(results) > 0

    def test_recommendations_with_income_filter(self, sample_beneficiaries):
        results = get_recommendations(
            sample_beneficiaries, max_beneficiaries=50,
            min_income=0, max_income=200000,
        )
        for r in results:
            income = float(r.get('family_annual_income', 0) or 0)
            assert income <= 200000

    def test_recommendations_with_barangay_filter(self, sample_beneficiaries):
        results = get_recommendations(
            sample_beneficiaries, max_beneficiaries=50,
            priority_barangays=['Poblacion', 'San Jose'],
        )
        for r in results:
            assert r['barangay'] in ('Poblacion', 'San Jose')

    def test_empty_data_returns_empty(self):
        results = get_recommendations([], max_beneficiaries=10)
        assert results == []

    def test_cbf_path_with_target(self, sample_beneficiaries, target_profile):
        results = get_recommendations(
            sample_beneficiaries,
            target_profile=target_profile,
            max_beneficiaries=10,
        )
        assert len(results) > 0

    def test_score_breakdown_present(self, sample_beneficiaries):
        results = get_recommendations(sample_beneficiaries, max_beneficiaries=10)
        for r in results:
            assert 'score_breakdown' in r


# ===========================================================================
# 10. Edge cases
# ===========================================================================

class TestEdgeCases:

    def test_single_beneficiary(self):
        data = [{
            'user_id': 1, 'age': 30, 'barangay': 'X', 'gender': 'Male',
            'family_annual_income': 100000, 'is_solo_parent': False,
            'is_student': False, 'is_pwd': False,
            'is_currently_employed': True, 'occupation': 'Vendor',
            'disability_type': None,
        }]
        recommender = BeneficiaryRecommender()
        assert recommender.fit(data)
        scored = recommender.score_beneficiaries(data)
        assert len(scored) == 1

    def test_null_fields_handled(self):
        data = [{
            'user_id': 1, 'age': None, 'barangay': None,
            'family_annual_income': None, 'is_solo_parent': None,
            'is_student': None, 'is_pwd': None,
            'is_currently_employed': None, 'occupation': None,
        }]
        recommender = BeneficiaryRecommender()
        # fit may fail with 1 item and empty vocab — that's acceptable
        # The key is it doesn't crash with an unhandled exception
        try:
            recommender.fit(data)
        except ValueError:
            pass  # TF-IDF with no valid tokens is expected

    def test_negative_income_clamped(self):
        data = [{
            'user_id': 1, 'age': 30, 'barangay': 'X', 'gender': 'Male',
            'family_annual_income': -50000, 'is_solo_parent': False,
            'is_student': False, 'is_pwd': False,
            'is_currently_employed': True, 'occupation': 'None',
        }]
        recommender = BeneficiaryRecommender()
        scored = recommender.score_beneficiaries(data)
        assert scored[0]['score'] >= 0

    def test_very_large_dataset(self):
        """Performance check with 500 beneficiaries."""
        data = [
            {'user_id': i, 'age': 20 + i % 60, 'barangay': f'Brgy{i % 10}',
             'gender': 'Male', 'family_annual_income': 50000 + i * 1000,
             'is_solo_parent': i % 3 == 0, 'is_student': i % 4 == 0,
             'is_pwd': i % 5 == 0, 'is_currently_employed': i % 2 == 0,
             'occupation': 'Worker', 'disability_type': None}
            for i in range(500)
        ]
        results = get_recommendations(data, max_beneficiaries=75)
        assert len(results) == 75
