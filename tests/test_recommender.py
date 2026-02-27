"""
Tests for the content-based beneficiary recommendation module.
"""
import pytest
from app.recommender import (
    BeneficiaryRecommender,
    get_recommendations
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
        """Test scoring with custom priority weights"""
        recommender = BeneficiaryRecommender()
        
        # Prioritize solo parents heavily
        priority_weights = {
            'low_income': 0.1,
            'solo_parent': 0.5,
            'student': 0.1,
            'pwd': 0.1
        }
        
        scored = recommender.score_beneficiaries(sample_beneficiaries, priority_weights)
        
        # Solo parent (Juan) should have highest score
        assert scored[0]['first_name'] == 'Juan'


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
        """Test recommendations with solo parent priority"""
        results = get_recommendations(
            sample_beneficiaries,
            solo_parent_priority=True
        )
        
        # Solo parent should be ranked higher
        solo_parents = [r for r in results if r['is_solo_parent']]
        if solo_parents:
            # Check that solo parent has higher score
            solo_parent_score = solo_parents[0]['score']
            non_solo_parent_scores = [r['score'] for r in results if not r['is_solo_parent']]
            # At least one non-solo parent should have lower score
            assert any(s < solo_parent_score for s in non_solo_parent_scores)
    
    def test_get_recommendations_pwd_priority(self, sample_beneficiaries):
        """Test recommendations with PWD priority"""
        results = get_recommendations(
            sample_beneficiaries,
            pwd_priority=True
        )
        
        # PWD beneficiaries should be ranked higher
        pwd_beneficiaries = [r for r in results if r['is_pwd']]
        assert len(pwd_beneficiaries) > 0
    
    def test_get_recommendations_student_priority(self, sample_beneficiaries):
        """Test recommendations with student priority"""
        results = get_recommendations(
            sample_beneficiaries,
            student_priority=True
        )
        
        # Students should be ranked higher
        students = [r for r in results if r['is_student']]
        assert len(students) > 0
    
    def test_get_recommendations_combined_priorities(self, sample_beneficiaries):
        """Test recommendations with multiple priorities"""
        results = get_recommendations(
            sample_beneficiaries,
            solo_parent_priority=True,
            pwd_priority=True,
            student_priority=True
        )
        
        # Juan (solo parent + PWD) should be first
        assert results[0]['first_name'] == 'Juan'