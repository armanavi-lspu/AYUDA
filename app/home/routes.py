from flask import Blueprint, render_template


home_bp = Blueprint('main', __name__)

@home_bp.route('/')
def about():
    return render_template('about.html')

@home_bp.route('/programs')
def programs():
    return render_template('programs.html')

@home_bp.route('/privacy')
def privacy():
    return render_template('securitynprivacy.html')
