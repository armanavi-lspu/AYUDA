#!/usr/bin/env python3
import re

with open('templates/admin/view_edit_program.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove openWorkflowModalImpl function and related code
content = re.sub(
    r'    function openWorkflowModalImpl\(\) \{.*?\n    \}\n    \n    // Handle modal cancel/close to discard temporary changes\n    \$\(\'#workflowModal\'\)\.on\(\'hidden\.bs\.modal\', function\(\) \{.*?\n    \}\);',
    '    // openWorkflowModalImpl() removed - modal no longer used',
    content,
    flags=re.DOTALL
)

# Remove renderWorkflowStepsModal function
content = re.sub(
    r'    \n    function renderWorkflowStepsModal\(\) \{.*?\n        \}\n    \}',
    '',
    content,
    flags=re.DOTALL
)

# Remove saveWorkflowStepsImpl function
content = re.sub(
    r'    \n    function saveWorkflowStepsImpl\(button\) \{.*?\n    \}',
    '    // saveWorkflowStepsImpl() removed - modal no longer used',
    content,
    flags=re.DOTALL
)

# Clean up extra blank lines
content = re.sub(r'\n\n\n+', '\n\n', content)

with open('templates/admin/view_edit_program.html', 'w', encoding='utf-8') as f:
    f.write(content)

print('Successfully cleaned up remaining modal functions')
