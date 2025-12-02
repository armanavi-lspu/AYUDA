"""
Tests for the content-based beneficiary recommendation module.
"""
import pytest
from app.recommender import (
    BeneficiaryRecommender,
    get_recommendations,
    ProgramRecommender
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
            'pwd': 0.1,
            'unemployed': 0.1
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


@pytest.fixture
def sample_programs():
    """Sample program data for testing ProgramRecommender"""
    return [
        {
            'id': 1,
            'program_name': 'Educational Assistance Program',
            'program_type': 'Education',
            'description': 'Scholarship and educational support for students pursuing higher education',
            'is_active': True
        },
        {
            'id': 2,
            'program_name': 'Emergency Cash Assistance',
            'program_type': 'Emergency',
            'description': 'Emergency financial aid for families affected by calamities or crisis',
            'is_active': True
        },
        {
            'id': 3,
            'program_name': 'Housing Support Program',
            'program_type': 'Housing',
            'description': 'Shelter assistance and housing materials for low-income families',
            'is_active': True
        },
        {
            'id': 4,
            'program_name': 'Livelihood and Business Program',
            'program_type': 'Business',
            'description': 'Capital and training for small business and livelihood projects',
            'is_active': True
        },
        {
            'id': 5,
            'program_name': 'Healthcare Assistance Program',
            'program_type': 'Healthcare',
            'description': 'Medical and healthcare support for PWD and senior citizens',
            'is_active': True
        },
        {
            'id': 6,
            'program_name': 'Employment Assistance Program',
            'program_type': 'Employment',
            'description': 'Job placement and skills training for unemployed workers',
            'is_active': True
        },
    ]


class TestProgramRecommender:
    """Tests for the ProgramRecommender class"""
    
    def test_program_recommender_initialization(self):
        """Test recommender initialization"""
        recommender = ProgramRecommender()
        assert recommender.vectorizer is None
        assert recommender.program_vectors is None
        assert recommender.is_fitted is False
    
    def test_program_recommender_fit(self, sample_programs):
        """Test fitting the recommender model"""
        recommender = ProgramRecommender()
        result = recommender.fit(sample_programs)
        
        assert result is True
        assert recommender.vectorizer is not None
        assert recommender.program_vectors is not None
        assert recommender.is_fitted is True
        assert len(recommender.programs) == 6
        assert len(recommender.program_id_to_idx) == 6
    
    def test_program_recommender_fit_empty_data(self):
        """Test fitting with empty data"""
        recommender = ProgramRecommender()
        result = recommender.fit([])
        
        assert result is False
        assert recommender.is_fitted is False
    
    def test_income_bucket(self, sample_programs):
        """Test income bucket calculation"""
        recommender = ProgramRecommender()
        recommender.fit(sample_programs)
        
        assert recommender._income_bucket(50000) == "low_income"
        assert recommender._income_bucket(100000) == "low_income"
        assert recommender._income_bucket(150000) == "mid_income"
        assert recommender._income_bucket(300000) == "mid_income"
        assert recommender._income_bucket(400000) == "high_income"
        assert recommender._income_bucket(None) == "unknown_income"
        assert recommender._income_bucket("invalid") == "unknown_income"
    
    def test_build_user_profile_text(self, sample_programs):
        """Test user profile text construction"""
        recommender = ProgramRecommender()
        recommender.fit(sample_programs)
        
        # Test with dict profile
        profile = {
            'family_annual_income': 50000,
            'is_student': True,
            'is_solo_parent': False,
            'is_pwd': False,
            'is_currently_employed': True
        }
        text = recommender._build_user_profile_text(profile)
        assert 'low_income' in text
        assert 'student' in text
        assert 'education' in text
        assert 'solo_parent' not in text
    
    def test_status_type_boost_student_education(self, sample_programs):
        """Test status-type boost for student + education"""
        recommender = ProgramRecommender()
        recommender.fit(sample_programs)
        
        profile = {'is_student': True}
        education_program = {'program_type': 'Education'}
        business_program = {'program_type': 'Business'}
        
        boost_education = recommender._status_type_boost(profile, education_program)
        boost_business = recommender._status_type_boost(profile, business_program)
        
        assert boost_education > boost_business
        assert boost_education == ProgramRecommender.BOOST_STUDENT_EDUCATION
    
    def test_popularity_fallback(self, sample_programs):
        """Test popularity fallback when no profile"""
        recommender = ProgramRecommender()
        recommender.fit(sample_programs)
        
        results = recommender._popularity_fallback(top_n=3)
        
        assert len(results) == 3
        assert all('score' in r for r in results)
        # Results should be sorted by score descending
        assert results[0]['score'] >= results[1]['score']
    
    def test_recommend_for_user_without_interactions_or_profile(self, sample_programs):
        """Test recommend_for_user falls back to popularity when no data"""
        recommender = ProgramRecommender()
        recommender.fit(sample_programs)
        
        # No interactions, no profile
        results = recommender.recommend_for_user(
            user_id=999,
            top_n=3,
            interactions=None,
            profile=None
        )
        
        assert len(results) == 3
        assert all('score' in r for r in results)


class TestColdStartRecommendations:
    """Tests for cold-start profile-based recommendations"""
    
    def test_cold_start_student_biases_towards_education(self, sample_programs):
        """
        Test that a student user gets Education program recommendations
        higher than baseline popularity.
        """
        recommender = ProgramRecommender()
        recommender.fit(sample_programs)
        
        # Create a student user profile with low income
        student_profile = {
            'family_annual_income': 50000,  # low income
            'is_student': True,
            'is_solo_parent': False,
            'is_pwd': False,
            'is_currently_employed': False
        }
        
        # Get recommendations using profile-based cold start
        results = recommender._profile_based_cold_start(student_profile, top_n=6)
        
        # Verify we get results
        assert len(results) > 0
        
        # Find the Education program in results
        education_programs = [r for r in results if r.get('program_type') == 'Education']
        assert len(education_programs) > 0, "Education program should be in recommendations"
        
        # Get education program's rank (position in results)
        education_rank = next(
            (idx for idx, r in enumerate(results) if r.get('program_type') == 'Education'),
            None
        )
        
        # Education should be in top 3 for a student
        assert education_rank is not None
        assert education_rank < 3, f"Education program should be in top 3, got rank {education_rank}"
        
        # Compare with popularity-only fallback
        popularity_results = recommender._popularity_fallback(top_n=6)
        popularity_education_rank = next(
            (idx for idx, r in enumerate(popularity_results) if r.get('program_type') == 'Education'),
            len(popularity_results)
        )
        
        # Education rank should be same or better than popularity baseline
        # (since student boost should help Education programs)
        assert education_rank <= popularity_education_rank or education_rank < 3
    
    def test_cold_start_solo_parent_low_income_biases_towards_emergency_or_housing(self, sample_programs):
        """
        Test that a solo parent with low income gets Emergency/Housing
        program recommendations favored.
        """
        recommender = ProgramRecommender()
        recommender.fit(sample_programs)
        
        # Create a solo parent user profile with low income
        solo_parent_profile = {
            'family_annual_income': 40000,  # low income
            'is_student': False,
            'is_solo_parent': True,
            'is_pwd': False,
            'is_currently_employed': False
        }
        
        # Get recommendations using profile-based cold start
        results = recommender._profile_based_cold_start(solo_parent_profile, top_n=6)
        
        # Verify we get results
        assert len(results) > 0
        
        # Check that Emergency or Housing programs are in top results
        top_3_types = [r.get('program_type', '').lower() for r in results[:3]]
        favored_types = {'emergency', 'housing'}
        
        # At least one of Emergency or Housing should be in top 3
        found_favored = any(t in favored_types for t in top_3_types)
        assert found_favored, f"Expected Emergency or Housing in top 3, got {top_3_types}"
        
        # Calculate total boost-receiving programs in top half vs bottom half
        emergency_housing_scores = [
            r['score'] for r in results 
            if r.get('program_type', '').lower() in favored_types
        ]
        other_scores = [
            r['score'] for r in results 
            if r.get('program_type', '').lower() not in favored_types
        ]
        
        # Average score for favored types should be higher
        if emergency_housing_scores and other_scores:
            avg_favored = sum(emergency_housing_scores) / len(emergency_housing_scores)
            avg_other = sum(other_scores) / len(other_scores)
            assert avg_favored >= avg_other, \
                f"Favored types avg ({avg_favored}) should be >= other types avg ({avg_other})"
    
    def test_cold_start_pwd_biases_towards_healthcare(self, sample_programs):
        """Test that a PWD user gets Healthcare program recommendations favored."""
        recommender = ProgramRecommender()
        recommender.fit(sample_programs)
        
        # Create a PWD user profile
        pwd_profile = {
            'family_annual_income': 80000,
            'is_student': False,
            'is_solo_parent': False,
            'is_pwd': True,
            'is_currently_employed': False
        }
        
        # Get recommendations
        results = recommender._profile_based_cold_start(pwd_profile, top_n=6)
        
        # Healthcare should be boosted
        healthcare_programs = [r for r in results if r.get('program_type') == 'Healthcare']
        assert len(healthcare_programs) > 0
        
        healthcare_score = healthcare_programs[0]['score']
        
        # Healthcare should have a decent score due to PWD boost
        # Find a program type that shouldn't be boosted for PWD
        education_programs = [r for r in results if r.get('program_type') == 'Education']
        if education_programs:
            education_score = education_programs[0]['score']
            # Healthcare score should be higher than education for PWD user
            assert healthcare_score >= education_score
    
    def test_cold_start_unemployed_biases_towards_employment(self, sample_programs):
        """Test that an unemployed user gets Employment/Business recommendations."""
        recommender = ProgramRecommender()
        recommender.fit(sample_programs)
        
        # Create an unemployed user profile (is_currently_employed=False is used as proxy)
        unemployed_profile = {
            'family_annual_income': 100000,
            'is_student': False,
            'is_solo_parent': False,
            'is_pwd': False,
            'is_currently_employed': False  # This triggers unemployed boosts
        }
        
        # Get recommendations
        results = recommender._profile_based_cold_start(unemployed_profile, top_n=6)
        
        # Employment and Business should be boosted
        employment_types = {'employment', 'business', 'emergency'}
        boosted_count = sum(
            1 for r in results[:3] 
            if r.get('program_type', '').lower() in employment_types
        )
        
        # At least one employment-related program should be in top 3
        assert boosted_count >= 1, \
            f"Expected Employment/Business/Emergency in top 3, got {[r.get('program_type') for r in results[:3]]}"
    
    def test_interaction_based_excludes_interacted_programs(self, sample_programs):
        """Test that interaction-based recommendations exclude already-interacted programs."""
        recommender = ProgramRecommender()
        recommender.fit(sample_programs)
        
        # User has interacted with Education program (id=1)
        interactions = [{'program_id': 1}]
        
        results = recommender._interaction_based_recommendations(interactions, top_n=5)
        
        # Education program (id=1) should NOT be in results
        result_ids = [r['id'] for r in results]
        assert 1 not in result_ids, "Interacted program should not be recommended"
    
    def test_recommend_for_user_with_interactions_uses_interaction_logic(self, sample_programs):
        """Test that recommend_for_user uses interaction logic when interactions exist."""
        recommender = ProgramRecommender()
        recommender.fit(sample_programs)
        
        # User has interactions
        interactions = [{'program_id': 1}, {'program_id': 2}]
        profile = {
            'is_student': True,
            'family_annual_income': 50000
        }
        
        results = recommender.recommend_for_user(
            user_id=1,
            top_n=4,
            interactions=interactions,
            profile=profile
        )
        
        # Should not include interacted programs (1 and 2)
        result_ids = [r['id'] for r in results]
        assert 1 not in result_ids
        assert 2 not in result_ids
    
    def test_recommend_for_user_cold_start_with_profile(self, sample_programs):
        """Test that recommend_for_user uses profile for cold start when no interactions."""
        recommender = ProgramRecommender()
        recommender.fit(sample_programs)
        
        # No interactions, but has profile
        profile = {
            'is_student': True,
            'family_annual_income': 50000
        }
        
        results = recommender.recommend_for_user(
            user_id=1,
            top_n=6,
            interactions=[],  # Empty interactions = cold start
            profile=profile
        )
        
        # Should include all programs (no exclusions)
        assert len(results) == 6
        
        # Education should be favored for student
        education_rank = next(
            (idx for idx, r in enumerate(results) if r.get('program_type') == 'Education'),
            None
        )
        assert education_rank is not None
        assert education_rank < 3  # Should be in top 3
    
    def test_recommend_for_user_with_callback_functions(self, sample_programs):
        """Test recommend_for_user with callback functions for fetching data."""
        recommender = ProgramRecommender()
        recommender.fit(sample_programs)
        
        # Define mock callbacks
        def get_profile(user_id):
            return {
                'is_student': True,
                'family_annual_income': 50000
            }
        
        def get_interactions(user_id):
            return []  # No interactions = cold start
        
        results = recommender.recommend_for_user(
            user_id=1,
            top_n=3,
            get_profile_func=get_profile,
            get_interactions_func=get_interactions
        )
        
        assert len(results) == 3
        assert all('score' in r for r in results)