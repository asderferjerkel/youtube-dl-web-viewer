import functools
import sqlite3

from flask import Blueprint, g, current_app, flash, redirect, render_template, request, session, url_for

from flask_wtf import FlaskForm
from wtforms import SubmitField

from app.auth import login_required
from app.db import get_db, get_params, get_log, clear_log
from app.api import list_folders

blueprint = Blueprint('index', __name__)

class ClearLogForm(FlaskForm):
	submit = SubmitField('Clear error log')

@blueprint.route('/')
@login_required('guest')
def index():
	# check if db needs updating: wrap with @request_queued (after login_required) + import from app.helpers
		 # see https://exploreflask.com/en/latest/views.html
		 # or just do in js
	# do the same for check_conf (change to @warn_conf)
	# could do the same for @require_db, @require_first_run
	# no video/folder selected to start, just folders
	  # so can supply http basic auth in html if necessary and use XHR to set headers
	  # https://stackoverflow.com/questions/3823357/how-to-set-the-img-tag-with-basic-authentication
	# feed w/ folder list
	# set some var if guest so JS doesn't call /api/status at all
	# many dangers: https://semgrep.dev/docs/cheat-sheets/flask-xss/ https://flask.palletsprojects.com/en/1.1.x/security/
	
	try:
		params = get_params()
	except sqlite3.OperationalError as e:
		flash('Failed to get params')
		current_app.logger.error('Failed to get params: ' + str(e))
	
	# Get list of playlists from database
	try:
		playlists = list_folders()
	except sqlite3.OperationalError as e:
		current_app.logger.error('Failed to list playlists: ' + str(e))
		flash('Failed to list playlists')
		playlists = None
	
	if len(playlists) == 0:
		playlists = None
		flash('No videos')
	
	api_available = False
	# Logged in users can access the API
	if g.user is not None:
		api_available = True
	
	last_refreshed = params['last_refreshed']
	
	return render_template('index.html', playlists = playlists, api_available = api_available, last_refreshed = last_refreshed)

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