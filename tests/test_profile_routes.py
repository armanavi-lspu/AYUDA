#!/usr/bin/env python
"""
Test the profile and settings feature routes.
"""

import sys
from app import create_app

def test_routes():
    """Test that all profile and settings routes are registered."""
    app = create_app()
    
    with app.app_context():
        routes = []
        for rule in app.url_map.iter_rules():
            if 'community' in rule.endpoint:
                if ('profile' in rule.endpoint or 'settings' in rule.endpoint or 
                    'change_password' in rule.endpoint or 'delete_account' in rule.endpoint or
                    'notification' in rule.endpoint):
                    routes.append({
                        'endpoint': rule.endpoint,
                        'methods': list(rule.methods - {'HEAD', 'OPTIONS'}),
                        'path': str(rule)
                    })
        
        print("✓ Profile and Settings Routes Registered:\n")
        for route in sorted(routes, key=lambda x: x['path']):
            methods = ', '.join(route['methods'])
            print(f"  {route['path']:<40} [{methods:<15}] → {route['endpoint']}")
        
        print(f"\n✓ Total routes: {len(routes)}")
        
        # Check for required routes
        required_endpoints = [
            'community.profile',
            'community.edit_profile',
            'community.settings',
            'community.change_password',
            'community.update_notification_settings',
            'community.delete_account'
        ]
        
        found_endpoints = [r['endpoint'] for r in routes]
        missing = [ep for ep in required_endpoints if ep not in found_endpoints]
        
        if missing:
            print(f"\n✗ Missing endpoints: {missing}")
            return False
        else:
            print("\n✓ All required endpoints are registered!")
            return True


if __name__ == '__main__':
    success = test_routes()
    sys.exit(0 if success else 1)
