import functools

from flask import Blueprint, g, current_app, flash, redirect, render_template, request, session, url_for

from flask_wtf import FlaskForm
from wtforms import SubmitField

from app.auth import login_required
from app.db import get_db, get_log, clear_log

blueprint = Blueprint('index', __name__)

class ClearLogForm(FlaskForm):
	submit = SubmitField('Clear error log')

@blueprint.route('/')
@login_required('guest')
def index():
	# check if db needs updating: wrap with @request_queued (after login_required) + import from app.helpers
		 # see https://exploreflask.com/en/latest/views.html
	# do the same for check_conf (change to @warn_conf)
	# could do the same for @require_db, @require_first_run
	# no video/folder selected to start
	# feed w/ folder list
	# set some var if guest so JS doesn't call /api/status at all
	# many dangers: https://semgrep.dev/docs/cheat-sheets/flask-xss/ https://flask.palletsprojects.com/en/1.1.x/security/
	current_app.logger.critical('test1')
	return render_template('index.html')

@blueprint.route('/log', methods=('GET', 'POST'))
@login_required('admin')
def error_log():
	log = None
	form = ClearLogForm()
	
	if form.validate_on_submit():
		try:
			clear_log()
		except sqlite3.OperationalError:
			flash('Could not clear log')
		else:
			flash('Log cleared')
			return redirect(url_for('index.error_log'))
	
	try:
		log = get_log()
	except sqlite3.OperationalError:
		flash('Could not get log')
	
	return render_template('error_log.html', title = 'Error log', log = log, form = form)