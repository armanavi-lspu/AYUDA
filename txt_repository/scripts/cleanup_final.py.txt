#!/usr/bin/env python3
"""
Comprehensive modal cleanup script.
Removes all unused modal HTML markup and JavaScript functions.
"""
import re

def clean_modals(content):
    """Remove all unused modal code from the template."""
    
    # 1. Remove programInfoModal HTML block (including nested script)
    # This is a large block starting with <!-- Program Information Edit Modal -->
    # and ending before <!-- Requirements Edit Modal -->
    content = re.sub(
        r'\n<!-- Program Information Edit Modal -->.*?<!-- Requirements Edit Modal -->',
        '\n<!-- Removed: programInfoModal HTML and script -->\n<!-- Requirements Edit Modal -->',
        content,
        count=1,
        flags=re.DOTALL
    )
    
    # 2. Remove requirementsModal HTML block
    # Starts with <!-- Requirements Edit Modal --> ends before <!-- Workflow Steps Edit Modal -->
    content = re.sub(
        r'\n<!-- Requirements Edit Modal -->.*?<!-- Workflow Steps Edit Modal -->',
        '\n<!-- Removed: requirementsModal HTML -->\n<!-- Workflow Steps Edit Modal -->',
        content,
        count=1,
        flags=re.DOTALL
    )
    
    # 3. Remove workflowModal HTML block
    # Starts with <!-- Workflow Steps Edit Modal --> ends before <!-- Unsaved Changes Confirmation Modal -->
    content = re.sub(
        r'\n<!-- Workflow Steps Edit Modal -->.*?<!-- Unsaved Changes Confirmation Modal -->',
        '\n<!-- Removed: workflowModal HTML -->\n<!-- Unsaved Changes Confirmation Modal -->',
        content,
        count=1,
        flags=re.DOTALL
    )
    
    # 4. Remove window.openProgramInfoModal wrapper function
    content = re.sub(
        r'\n\s+window\.openProgramInfoModal = function\(\) \{.*?\n\s+\};\n',
        '\n',
        content,
        flags=re.DOTALL
    )
    
    # 5. Remove window.openRequirementsModal wrapper function
    content = re.sub(
        r'\n\s+window\.openRequirementsModal = function\(\) \{.*?\n\s+\};\n',
        '\n',
        content,
        flags=re.DOTALL
    )
    
    # 6. Remove window.openWorkflowModal wrapper function
    content = re.sub(
        r'\n\s+window\.openWorkflowModal = function\(\) \{.*?\n\s+\};\n',
        '\n',
        content,
        flags=re.DOTALL
    )
    
    # 7. Remove comment marker for modal section if present
    content = re.sub(
        r'    // ===================================\n    // MODAL EDITING FUNCTIONS\n    // ===================================\n',
        '',
        content
    )
    
    # 8. Remove openProgramInfoModalImpl function
    content = re.sub(
        r'\n    function openProgramInfoModalImpl\(\) \{.*?\n    \}\n',
        '\n',
        content,
        flags=re.DOTALL
    )
    
    # 9. Remove saveProgramInfo function
    content = re.sub(
        r'\n    function saveProgramInfo\(button\) \{.*?\n    \}\n',
        '\n',
        content,
        flags=re.DOTALL
    )
    
    # 10. Remove openRequirementsModalImpl function
    content = re.sub(
        r'\n    function openRequirementsModalImpl\(\) \{.*?(?=\n    function toggleCopyFields)',
        '\n',
        content,
        flags=re.DOTALL
    )
    
    # 11. Remove toggleCopyFields function (modal-only, use toggleCopyFieldsEdit instead)
    content = re.sub(
        r'\n    function toggleCopyFields\(reqId, isChecked\) \{.*?\n    \}\n',
        '\n',
        content,
        flags=re.DOTALL
    )
    
    # 12. Remove saveRequirements function
    content = re.sub(
        r'\n    function saveRequirements\(button\) \{.*?(?=\n    function openWorkflowModalImpl)',
        '\n',
        content,
        flags=re.DOTALL
    )
    
    # 13. Remove openWorkflowModalImpl and modal close handler
    content = re.sub(
        r'\n    function openWorkflowModalImpl\(\) \{.*?\n    \}\n    \n    // Handle modal cancel/close.*?\n    \}\);\n',
        '\n',
        content,
        flags=re.DOTALL
    )
    
    # 14. Remove renderWorkflowStepsModal function
    content = re.sub(
        r'\n    function renderWorkflowStepsModal\(\) \{.*?(?=\n    function saveWorkflowStepsImpl)',
        '\n',
        content,
        flags=re.DOTALL
    )
    
    # 15. Remove saveWorkflowStepsImpl function
    content = re.sub(
        r'\n    function saveWorkflowStepsImpl\(button\) \{.*?(?=\n    \}.*?\n.*?window\.)',
        '\n',
        content,
        flags=re.DOTALL
    )
    
    # Clean up excessive blank lines
    content = re.sub(r'\n\n\n+', '\n\n', content)
    
    return content

if __name__ == '__main__':
    with open('templates/admin/view_edit_program.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    content = clean_modals(content)
    
    with open('templates/admin/view_edit_program.html', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print('✓ Successfully removed all unused modal code')
    print('✓ Template is now ready for use with tab-based navigation only')
