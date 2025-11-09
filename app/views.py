from flask import Blueprint, render_template, request, flash, jsonify
from flask_login import login_required, current_user
from .models import Programs
from . import db
import json

views = Blueprint('views', __name__)

@views.route('/', methods=['GET'])
def about():
    return render_template("about.html", user=current_user)

@views.route('/home', methods = ['POST', 'GET'])
@login_required
def home(): 
    if request.method == 'POST':
        note = request.form.get('note')

        if len(note) < 1:
            flash('Note is too short', category='error')
        else:  
            new_note = Programs(data=note, user_id = current_user.id)
            db.session.add(new_note)
            db.session.commit()
            flash('Note added', category='success')
    return render_template("community/dashboard.html", user = current_user)

@views.route('/delete-note', methods = ['POST'])
def delete_note():
    data = json.loads(request.data)  # Changed from json.load to json.loads
    noteId = data['noteId']  # Use 'data' variable and correct key name
    note = Programs.query.get(noteId)
    if note: 
        if note.user_id == current_user.id:
            db.session.delete(note)
            db.session.commit()
            
    return jsonify({})