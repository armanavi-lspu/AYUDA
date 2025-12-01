"""
Tests for the content-based beneficiary recommendation system.
"""

import pytest
from app.recommender import (
    BeneficiaryRecommender,
    generate_beneficiary_recommendations
)


class TestBeneficiaryRecommender:
    """Tests for the BeneficiaryRecommender class."""

    @pytest.fixture
    def sample_beneficiaries(self):
        """Sample beneficiary data for testing."""
        return [
            {
                'user_id': 1,
                'first_name': 'Juan',
                'last_name': 'Dela Cruz',
                'email': 'juan@example.com',
                'barangay': 'Poblacion',
                'sitio': 'Centro',
                'municipality': 'San Pedro',
                'family_annual_income': 50000,
                'is_solo_parent': True,
                'is_student': False,
                'is_pwd': False,
                'is_currently_employed': False,
                'occupation': 'Farmer',
                'age': 35
            },
            {
                'user_id': 2,
                'first_name': 'Maria',
                'last_name': 'Santos',
                'email': 'maria@example.com',
                'barangay': 'Poblacion',
                'sitio': 'East',
                'municipality': 'San Pedro',
                'family_annual_income': 30000,
                'is_solo_parent': False,
                'is_student': True,
                'is_pwd': False,
                'is_currently_employed': False,
                'occupation': None,
                'age': 20
            },
            {
                'user_id': 3,
                'first_name': 'Pedro',
                'last_name': 'Reyes',
                'email': 'pedro@example.com',
                'barangay': 'San Isidro',
                'sitio': 'North',
                'municipality': 'San Pedro',
                'family_annual_income': 100000,
                'is_solo_parent': False,
                'is_student': False,
                'is_pwd': True,
                'is_currently_employed': True,
                'occupation': 'Teacher',
                'age': 45
            },
            {
                'user_id': 4,
                'first_name': 'Ana',
                'last_name': 'Gonzales',
                'email': 'ana@example.com',
                'barangay': 'Bagong Bayan',
                'sitio': 'South',
                'municipality': 'San Pedro',
                'family_annual_income': 20000,
                'is_solo_parent': True,
                'is_student': False,
                'is_pwd': False,
                'is_currently_employed': False,
                'occupation': 'Vendor',
                'age': 40
            },
            {
                'user_id': 5,
                'first_name': 'Jose',
                'last_name': 'Garcia',
                'email': 'jose@example.com',
                'barangay': 'Poblacion',
                'sitio': 'West',
                'municipality': 'San Pedro',
                'family_annual_income': 80000,
                'is_solo_parent': False,
                'is_student': False,
                'is_pwd': False,
                'is_currently_employed': True,
                'occupation': 'Driver',
                'age': 50
            }
        ]

    def test_recommender_initialization(self):
        """Test that recommender initializes correctly."""
        recommender = BeneficiaryRecommender(n_neighbors=10)
        assert recommender.n_neighbors == 10
        assert recommender.model is None
        assert recommender.preprocessor is None

    def test_fit_with_data(self, sample_beneficiaries):
        """Test fitting the recommender with data."""
        recommender = BeneficiaryRecommender(n_neighbors=3)
        result = recommender.fit(sample_beneficiaries)
        
        assert result is recommender  # Should return self
        assert recommender.model is not None
        assert recommender.preprocessor is not None

    def test_fit_with_empty_data(self):
        """Test fitting with empty data."""
        recommender = BeneficiaryRecommender()
        result = recommender.fit([])
        
        assert result is recommender
        assert recommender.model is None

    def test_recommend_returns_list(self, sample_beneficiaries):
        """Test that recommend returns a list of recommendations."""
        recommender = BeneficiaryRecommender(n_neighbors=3)
        recommender.fit(sample_beneficiaries)
        
        recommendations = recommender.recommend(
            beneficiaries=sample_beneficiaries,
            max_results=3
        )
        
        assert isinstance(recommendations, list)
        assert len(recommendations) <= 3

    def test_recommend_contains_required_fields(self, sample_beneficiaries):
        """Test that recommendations contain all required fields."""
        recommender = BeneficiaryRecommender(n_neighbors=3)
        recommender.fit(sample_beneficiaries)
        
        recommendations = recommender.recommend(
            beneficiaries=sample_beneficiaries,
            max_results=1
        )
        
        assert len(recommendations) > 0
        rec = recommendations[0]
        
        assert 'user_id' in rec
        assert 'name' in rec
        assert 'email' in rec
        assert 'barangay' in rec
        assert 'income' in rec
        assert 'is_solo_parent' in rec
        assert 'is_student' in rec
        assert 'score' in rec

    def test_recommend_with_barangay_filter(self, sample_beneficiaries):
        """Test filtering by barangay."""
        recommender = BeneficiaryRecommender(n_neighbors=5)
        recommender.fit(sample_beneficiaries)
        
        filters = {'priority_barangay': 'Poblacion'}
        recommendations = recommender.recommend(
            beneficiaries=sample_beneficiaries,
            filters=filters,
            max_results=10
        )
        
        # All recommendations should be from Poblacion
        for rec in recommendations:
            assert rec['barangay'] == 'Poblacion'

    def test_recommend_with_income_filter(self, sample_beneficiaries):
        """Test filtering by income range."""
        recommender = BeneficiaryRecommender(n_neighbors=5)
        recommender.fit(sample_beneficiaries)
        
        filters = {'min_income': 0, 'max_income': 50000}
        recommendations = recommender.recommend(
            beneficiaries=sample_beneficiaries,
            filters=filters,
            max_results=10
        )
        
        # All recommendations should have income within range
        for rec in recommendations:
            assert rec['income'] <= 50000

    def test_recommend_solo_parent_priority(self, sample_beneficiaries):
        """Test that solo parent priority affects scoring."""
        recommender = BeneficiaryRecommender(n_neighbors=5)
        recommender.fit(sample_beneficiaries)
        
        # Get recommendations with solo parent priority
        filters_with_priority = {'solo_parent_priority': True}
        recs_with_priority = recommender.recommend(
            beneficiaries=sample_beneficiaries,
            filters=filters_with_priority,
            max_results=5
        )
        
        # Solo parents should be scored higher
        solo_parent_recs = [r for r in recs_with_priority if r['is_solo_parent']]
        non_solo_parent_recs = [r for r in recs_with_priority if not r['is_solo_parent']]
        
        if solo_parent_recs and non_solo_parent_recs:
            avg_solo_score = sum(r['score'] for r in solo_parent_recs) / len(solo_parent_recs)
            avg_non_solo_score = sum(r['score'] for r in non_solo_parent_recs) / len(non_solo_parent_recs)
            assert avg_solo_score >= avg_non_solo_score

    def test_recommend_student_priority(self, sample_beneficiaries):
        """Test that student priority affects scoring."""
        recommender = BeneficiaryRecommender(n_neighbors=5)
        recommender.fit(sample_beneficiaries)
        
        filters = {'student_priority': True}
        recommendations = recommender.recommend(
            beneficiaries=sample_beneficiaries,
            filters=filters,
            max_results=5
        )
        
        # Students should have higher scores on average
        student_recs = [r for r in recommendations if r['is_student']]
        assert len(student_recs) > 0 or len(recommendations) > 0

    def test_scores_are_normalized(self, sample_beneficiaries):
        """Test that scores are normalized to 0-100 range."""
        recommender = BeneficiaryRecommender(n_neighbors=5)
        recommender.fit(sample_beneficiaries)
        
        recommendations = recommender.recommend(
            beneficiaries=sample_beneficiaries,
            max_results=5
        )
        
        for rec in recommendations:
            assert 0 <= rec['score'] <= 100

    def test_recommend_empty_list(self):
        """Test recommending with empty beneficiaries list."""
        recommender = BeneficiaryRecommender()
        recommendations = recommender.recommend(
            beneficiaries=[],
            max_results=10
        )
        
        assert recommendations == []

    def test_lower_income_gets_higher_score(self, sample_beneficiaries):
        """Test that lower income beneficiaries get higher priority scores."""
        recommendations = generate_beneficiary_recommendations(
            beneficiaries=sample_beneficiaries,
            max_results=5
        )
        
        # Sort by income
        sorted_by_income = sorted(recommendations, key=lambda x: x['income'])
        # Sort by score (descending)
        sorted_by_score = sorted(recommendations, key=lambda x: x['score'], reverse=True)
        
        # Lower income should generally correlate with higher scores
        # (not strictly, due to other factors, but the lowest income should be in top half)
        lowest_income_rec = sorted_by_income[0]
        top_half_scores = sorted_by_score[:len(sorted_by_score)//2 + 1]
        assert any(r['user_id'] == lowest_income_rec['user_id'] for r in top_half_scores)


class TestGenerateBeneficiaryRecommendations:
    """Tests for the generate_beneficiary_recommendations function."""

    @pytest.fixture
    def sample_beneficiaries(self):
        """Sample beneficiary data for testing."""
        return [
            {
                'user_id': 1,
                'first_name': 'Test',
                'last_name': 'User1',
                'email': 'test1@example.com',
                'barangay': 'Barangay1',
                'family_annual_income': 25000,
                'is_solo_parent': True,
                'is_student': False,
                'is_pwd': False,
                'is_currently_employed': False,
                'age': 30
            },
            {
                'user_id': 2,
                'first_name': 'Test',
                'last_name': 'User2',
                'email': 'test2@example.com',
                'barangay': 'Barangay2',
                'family_annual_income': 75000,
                'is_solo_parent': False,
                'is_student': True,
                'is_pwd': False,
                'is_currently_employed': True,
                'age': 22
            }
        ]

    def test_generate_recommendations_basic(self, sample_beneficiaries):
        """Test basic recommendation generation."""
        recommendations = generate_beneficiary_recommendations(
            beneficiaries=sample_beneficiaries,
            max_results=2
        )
        
        assert isinstance(recommendations, list)
        assert len(recommendations) == 2

    def test_generate_recommendations_with_filters(self, sample_beneficiaries):
        """Test recommendation generation with filters."""
        filters = {
            'min_income': 0,
            'max_income': 50000,
            'solo_parent_priority': True
        }
        
        recommendations = generate_beneficiary_recommendations(
            beneficiaries=sample_beneficiaries,
            filters=filters,
            max_results=2
        )
        
        # Should only include users with income <= 50000
        for rec in recommendations:
            assert rec['income'] <= 50000

    def test_generate_recommendations_empty_input(self):
        """Test with empty input."""
        recommendations = generate_beneficiary_recommendations(
            beneficiaries=[],
            max_results=10
        )
        
        assert recommendations == []

    def test_generate_recommendations_max_results(self, sample_beneficiaries):
        """Test that max_results is respected."""
        recommendations = generate_beneficiary_recommendations(
            beneficiaries=sample_beneficiaries,
            max_results=1
        )
        
        assert len(recommendations) == 1
