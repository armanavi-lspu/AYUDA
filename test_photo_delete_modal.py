"""
Test file to verify that the photo delete modal functionality is properly implemented
"""

import re
from pathlib import Path

def test_delete_modal_html():
    """Verify the delete confirmation modal HTML exists in the template"""
    template_path = Path('templates/community/application_workflow.html')
    template_content = template_path.read_text()
    
    # Check for modal HTML structure
    assert 'deletePhotoConfirmModal' in template_content, "Modal ID not found"
    assert 'Delete Photo' in template_content, "Modal title not found"
    assert 'id="deletePhotoId"' in template_content, "Hidden input for photoId not found"
    assert 'onclick="confirmDeletePhoto()"' in template_content, "confirmDeletePhoto button not found"
    
    print("[VERIFIED] Delete modal HTML structure is present")


def test_delete_button_integration():
    """Verify that delete buttons are properly wired to the modal"""
    template_path = Path('templates/community/application_workflow.html')
    template_content = template_path.read_text()
    
    # Check for button attributes - more flexible pattern
    modal_trigger_pattern = r'setPhotoForDelete\(\{\{.*?\}\}\)'
    modal_target_pattern = r'data-target="#deletePhotoConfirmModal"'
    
    modal_calls = re.findall(modal_trigger_pattern, template_content)
    modal_targets = re.findall(modal_target_pattern, template_content)
    
    assert len(modal_calls) >= 2, f"Expected at least 2 setPhotoForDelete calls, found {len(modal_calls)}"
    assert len(modal_targets) >= 2, f"Expected at least 2 modal targets, found {len(modal_targets)}"
    
    print(f"[VERIFIED] Found {len(modal_calls)} delete buttons properly wired to modal")


def test_javascript_functions():
    """Verify that the required JavaScript functions are defined"""
    template_path = Path('templates/community/application_workflow.html')
    template_content = template_path.read_text()
    
    # Check for function definitions
    assert 'function setPhotoForDelete(photoId)' in template_content, "setPhotoForDelete function not found"
    assert 'function confirmDeletePhoto()' in template_content, "confirmDeletePhoto function not found"
    
    # Check for key operations
    assert "document.getElementById('deletePhotoId').value = photoId" in template_content, "Photo ID assignment not found"
    assert "fetch(`/community/applications/${applicationId}/delete-workflow-photo/${photoId}`" in template_content, "Delete API call not found"
    assert "updatePhotoCount(data.total_photos, data.has_min_photos)" in template_content, "Photo count update not found"
    
    print("[VERIFIED] All required JavaScript functions are properly defined")


def test_api_endpoint_exists():
    """Verify the delete API endpoint is properly configured"""
    from app import create_app
    
    app = create_app()
    
    # Check if the delete endpoint is registered
    routes = [rule.rule for rule in app.url_map.iter_rules()]
    delete_routes = [r for r in routes if 'delete-workflow-photo' in r]
    
    assert len(delete_routes) > 0, "Delete workflow photo endpoint not found"
    
    print(f"[VERIFIED] Delete API endpoint found: {delete_routes[0]}")


def test_modal_transitions():
    """Verify modal close/open transitions are properly handled"""
    template_path = Path('templates/community/application_workflow.html')
    template_content = template_path.read_text()
    
    # Check for modal operations
    assert "$('#deletePhotoConfirmModal').modal('hide')" in template_content, "Modal hide operation not found"
    assert "data-dismiss=\"modal\"" in template_content, "Modal close button not found"
    
    print("[VERIFIED] Modal transitions are properly configured")


if __name__ == '__main__':
    print("\n" + "="*60)
    print("Testing Photo Delete Modal Implementation")
    print("="*60 + "\n")
    
    try:
        test_delete_modal_html()
        test_delete_button_integration()
        test_javascript_functions()
        test_api_endpoint_exists()
        test_modal_transitions()
        
        print("\n" + "="*60)
        print("[SUCCESS] All photo delete modal tests passed!")
        print("="*60)
        
    except AssertionError as e:
        print(f"\n[ERROR] Test failed: {e}")
        print("="*60)
        exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        print("="*60)
        exit(1)
