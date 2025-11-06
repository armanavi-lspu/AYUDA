from flask import render_template
from flask_login import login_required, current_user
from .. import community

@community.route('/dashboard')
@login_required
def dashboard():
    return render_template('community/dashboard.html', user=current_user)