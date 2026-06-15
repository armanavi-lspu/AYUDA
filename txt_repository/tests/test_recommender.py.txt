"""
Tests for the content-based beneficiary recommendation module.
"""
import pytest
from app.recommender import (
    BeneficiaryRecommender,
    get_recommendations,
    _income_vulnerability_score,
)


@pytest.fixture
def sample_beneficiaries():
    """Sample beneficiary data for testing - shared across all test classes"""
    return [
        {
            'user_id': 1, 'first_name': 'Juan', 'last_name': 'Dela Cruz',
            'email': 'juan@test.com', 'age': 35, 'barangay': 'Poblacion',
            'family_annual_income': 50000, 'is_solo_parent': True,
            'is_student': False, 'is_pwd': True,
            'is_currently_employed': False, 'occupation': 'None'
        },
        {
            'user_id': 2, 'first_name': 'Maria', 'last_name': 'Santos',
            'email': 'maria@test.com', 'age': 28, 'barangay': 'Bagong Silang',
            'family_annual_income': 120000, 'is_solo_parent': False,
            'is_student': True, 'is_pwd': False,
            'is_currently_employed': True, 'occupation': 'Teacher'
        },
        {
            'user_id': 3, 'first_name': 'Pedro', 'last_name': 'Garcia',
            'email': 'pedro@test.com', 'age': 45, 'barangay': 'Poblacion',
            'family_annual_income': 30000, 'is_solo_parent': False,
            'is_student': False, 'is_pwd': False,
            'is_currently_employed': False, 'occupation': 'Farmer'
        },
        {
            'user_id': 4, 'first_name': 'Ana', 'last_name': 'Lopez',
            'email': 'ana@test.com', 'age': 22, 'barangay': 'San Jose',
            'family_annual_income': 80000, 'is_solo_parent': False,
            'is_student': True, 'is_pwd': True,
            'is_currently_employed': False, 'occupation': 'Student'
        },
    ]


class TestBeneficiaryRecommender:
    """Tests for the BeneficiaryRecommender class"""
    
    def test_recommender_initialization(self):
        """Test recommender initialization"""
        recommender = BeneficiaryRecommender()
        assert recommender.model is None
        assert recommender.preprocessor is None
    
    def test_recommender_fit(self, sample_beneficiaries):
        """Test fitting the recommender model"""
        recommender = BeneficiaryRecommender()
        result = recommender.fit(sample_beneficiaries)
        
        assert result is True
        assert recommender.model is not None
        assert recommender.beneficiary_data is not None
    
    def test_recommender_fit_empty_data(self):
        """Test fitting with empty data"""
        recommender = BeneficiaryRecommender()
        result = recommender.fit([])
        
        assert result is False
    
    def test_score_beneficiaries(self, sample_beneficiaries):
        """Test scoring beneficiaries"""
        recommender = BeneficiaryRecommender()
        scored = recommender.score_beneficiaries(sample_beneficiaries)
        
        assert len(scored) == 4
        assert all('score' in b for b in scored)
        # Should be sorted by score descending
        assert scored[0]['score'] >= scored[1]['score']
        assert scored[1]['score'] >= scored[2]['score']
    
    def test_score_with_priority_weights(self, sample_beneficiaries):
        """Priority-weight input should not alter finalized need-focused formula."""
        recommender = BeneficiaryRecommender()

        # Input is accepted for compatibility but ignored by finalized scoring.
        priority_weights = {
            'low_income': 1.0,
            'solo_parent': 0.9,
            'student': 0.9,
            'pwd': 0.9
        }

        scored = recommender.score_beneficiaries(sample_beneficiaries, priority_weights)

        # Juan ranks first due to combined household + income vulnerability.
        assert scored[0]['first_name'] == 'Juan'

    def test_score_beneficiaries_respects_scoring_parameters(self, sample_beneficiaries):
        """Disabled scoring factors should have zero weight and zero contribution."""
        recommender = BeneficiaryRecommender()
        scored = recommender.score_beneficiaries(
            sample_beneficiaries,
            scoring_parameters={
                'case_severity': False,
                'income_vulnerability': True,
                'household_vulnerability': True,
                'repeat_beneficiary_penalty': True,
            },
        )

        assert scored
        for beneficiary in scored:
            factor = beneficiary['score_breakdown']['case_severity_factor']
            assert factor['weight'] == 0.0
            assert factor['contribution'] == 0.0

    def test_score_beneficiaries_applies_custom_scoring_weights(self, sample_beneficiaries):
        """Custom scoring weights should be normalized and reflected in breakdown."""
        recommender = BeneficiaryRecommender()
        scored = recommender.score_beneficiaries(
            sample_beneficiaries,
            scoring_weights={
                'case_severity': 80,
                'income_vulnerability': 10,
                'household_vulnerability': 10,
                'repeat_beneficiary_penalty': 0,
            },
        )

        assert scored
        breakdown = scored[0]['score_breakdown']
        assert pytest.approx(breakdown['case_severity_factor']['weight'], rel=1e-6) == 0.8
        assert pytest.approx(breakdown['income_vulnerability_factor']['weight'], rel=1e-6) == 0.1
        assert pytest.approx(breakdown['household_vulnerability_factor']['weight'], rel=1e-6) == 0.1
        assert breakdown['repeat_beneficiary_penalty_factor']['weight'] == 0.0


class TestGetRecommendations:
    """Tests for the get_recommendations function"""
    
    def test_get_recommendations_basic(self, sample_beneficiaries):
        """Test basic recommendations generation"""
        results = get_recommendations(sample_beneficiaries)
        
        assert len(results) > 0
        assert all('score' in r for r in results)
    
    def test_get_recommendations_empty_data(self):
        """Test recommendations with empty data"""
        results = get_recommendations([])
        assert results == []
    
    def test_get_recommendations_with_max(self, sample_beneficiaries):
        """Test recommendations with max limit"""
        results = get_recommendations(sample_beneficiaries, max_beneficiaries=2)
        assert len(results) == 2
    
    def test_get_recommendations_income_filter(self, sample_beneficiaries):
        """Test recommendations with income filter"""
        results = get_recommendations(
            sample_beneficiaries,
            min_income=40000,
            max_income=100000
        )
        
        # Should only include those with income 50000-80000
        for r in results:
            assert 40000 <= r['family_annual_income'] <= 100000
    
    def test_get_recommendations_barangay_filter(self, sample_beneficiaries):
        """Test recommendations with barangay filter"""
        results = get_recommendations(
            sample_beneficiaries,
            priority_barangays=['Poblacion']
        )
        
        # Should only include Poblacion residents
        for r in results:
            assert r['barangay'] == 'Poblacion'
    
    def test_get_recommendations_multiple_barangays(self, sample_beneficiaries):
        """Test recommendations with multiple barangay filter"""
        results = get_recommendations(
            sample_beneficiaries,
            priority_barangays=['Poblacion', 'San Jose']
        )
        
        # Should only include Poblacion and San Jose residents
        for r in results:
            assert r['barangay'] in ['Poblacion', 'San Jose']
    
    def test_get_recommendations_solo_parent_priority(self, sample_beneficiaries):
        """Solo-parent flag should not change score-based ordering."""
        baseline = get_recommendations(sample_beneficiaries)
        results = get_recommendations(
            sample_beneficiaries,
            solo_parent_priority=True
        )

        assert [r['user_id'] for r in results] == [r['user_id'] for r in baseline]
    
    def test_get_recommendations_pwd_priority(self, sample_beneficiaries):
        """PWD flag should not change score-based ordering."""
        baseline = get_recommendations(sample_beneficiaries)
        results = get_recommendations(
            sample_beneficiaries,
            pwd_priority=True
        )

        assert [r['user_id'] for r in results] == [r['user_id'] for r in baseline]
    
    def test_get_recommendations_student_priority(self, sample_beneficiaries):
        """Student flag should not change score-based ordering."""
        baseline = get_recommendations(sample_beneficiaries)
        results = get_recommendations(
            sample_beneficiaries,
            student_priority=True
        )

        assert [r['user_id'] for r in results] == [r['user_id'] for r in baseline]
    
    def test_get_recommendations_combined_priorities(self, sample_beneficiaries):
        """Combined priority flags should not change score-based ordering."""
        baseline = get_recommendations(sample_beneficiaries)
        results = get_recommendations(
            sample_beneficiaries,
            solo_parent_priority=True,
            pwd_priority=True,
            student_priority=True
        )

        assert [r['user_id'] for r in results] == [r['user_id'] for r in baseline]

    def test_get_recommendations_with_scoring_parameters(self, sample_beneficiaries):
        """get_recommendations should pass scoring-parameter toggles into breakdown."""
        results = get_recommendations(
            sample_beneficiaries,
            scoring_parameters={
                'case_severity': True,
                'income_vulnerability': False,
                'household_vulnerability': True,
                'repeat_beneficiary_penalty': False,
            },
        )

        assert results
        for beneficiary in results:
            breakdown = beneficiary['score_breakdown']
            assert breakdown['income_vulnerability_factor']['weight'] == 0.0
            assert breakdown['income_vulnerability_factor']['contribution'] == 0.0
            assert breakdown['repeat_beneficiary_penalty_factor']['weight'] == 0.0
            assert breakdown['repeat_beneficiary_penalty_factor']['contribution'] == 0.0

    def test_get_recommendations_with_custom_scoring_weights(self, sample_beneficiaries):
        """get_recommendations should honor custom scoring weights."""
        results = get_recommendations(
            sample_beneficiaries,
            scoring_weights={
                'case_severity': 50,
                'income_vulnerability': 50,
                'household_vulnerability': 0,
                'repeat_beneficiary_penalty': 0,
            },
        )

        assert results
        for beneficiary in results:
            breakdown = beneficiary['score_breakdown']
            assert pytest.approx(breakdown['case_severity_factor']['weight'], rel=1e-6) == 0.5
            assert pytest.approx(breakdown['income_vulnerability_factor']['weight'], rel=1e-6) == 0.5
            assert breakdown['household_vulnerability_factor']['weight'] == 0.0
            assert breakdown['repeat_beneficiary_penalty_factor']['weight'] == 0.0


class TestIncomeRangeBasedScoring:
    """Regression tests for range-based income storage in community profiles."""

    def test_income_vulnerability_distinguishes_range_minimum_values(self):
        # Stored profile values are the selected range minimums.
        below_10k = _income_vulnerability_score(0)
        between_10k_20k = _income_vulnerability_score(10000)
        between_20k_30k = _income_vulnerability_score(20001)
        between_75k_100k = _income_vulnerability_score(75001)

        assert below_10k > between_10k_20k
        assert between_10k_20k > between_20k_30k
        assert between_20k_30k > between_75k_100k