from importlib import import_module

from flask import Blueprint

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Import routes after blueprint creation so view functions are registered.
# Using explicit module imports avoids edge cases with namespace-package imports.
for route_module in (
	'app.admin.routes.dashboard',
	'app.admin.routes.adm_announcements',
	'app.admin.routes.adm_programs',
	'app.admin.routes.analytics',
	'app.admin.routes.activity_logs',
	'app.admin.routes.admins',
	'app.admin.routes.community',
	'app.admin.routes.applications',
	'app.admin.routes.assessment',
	'app.admin.routes.notifications',
	'app.admin.routes.profile',
):
	import_module(route_module)
