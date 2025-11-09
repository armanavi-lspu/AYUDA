from flask import render_template
from flask_login import login_required, current_user
from app.community import community_bp
from app.utils import role_required

@community_bp.route('/other_services')
@login_required
@role_required('community')
def other_services():
    return render_template('community/other_services.html', user=current_user)