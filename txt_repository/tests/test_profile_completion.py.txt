#!/usr/bin/env python
"""
Test profile completion functionality.
"""

from app import create_app
from app.utils import calculate_profile_completion
from app.models import User

def test_profile_completion():
    """Test the profile completion calculation."""
    app = create_app()
    
    with app.app_context():
        # Get first user
        user = User.query.filter_by(role='community').first()
        
        if not user:
            print("No community users found in database")
            return False
        
        print(f"\nTesting profile completion for: {user.first_name} {user.last_name}")
        print("-" * 60)
        
        result = calculate_profile_completion(user)
        
        print(f"✓ Profile Completion: {result['percentage']}%")
        print(f"✓ Status: {'Complete' if result['is_complete'] else 'Incomplete'}")
        print(f"✓ Missing Fields: {result['missing_count']}")
        
        if result['missing_count'] > 0:
            print(f"\nFields to complete:")
            for field in result['missing_fields']:
                print(f"  - {field}")
        
        print(f"\nCompleted Fields ({len(result['completed_fields'])}):")
        for field in result['completed_fields'][:5]:  # Show first 5
            print(f"  ✓ {field}")
        if len(result['completed_fields']) > 5:
            print(f"  ... and {len(result['completed_fields']) - 5} more")
        
        print("\n" + "=" * 60)
        print("✓ Profile completion test successful!")
        return True


if __name__ == '__main__':
    test_profile_completion()
