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

@blueprint.route('/', defaults = {'item_type': None, 'item_id': None})
@blueprint.route('/<string:item_type>/<int:item_id>')
@login_required('guest')
def index(item_type, item_id):
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
	
	# Load item from URL on page load
	load_item = {'type': item_type, 'id': item_id}
	
	# Default display prefs for logged-out users (no cookies stored so resets with page load)
	display_prefs = {'autoplay': True,
					 'shuffle': False,
					 'sort_by': 'playlist_index',
					 'sort_direction': 'desc'}
	
	# Logged in users can access the API
	api_available = False
	if g.user is not None:
		if params['last_refreshed'] != 0:
			# Autorefresh doesn't trigger until db has been refreshed once
			api_available = True
		if 'display_prefs' in session:
			# Logged in users store display prefs per session
			display_prefs = session['display_prefs']
	
	return render_template('index.html', playlists = playlists, load_item = load_item, api_available = api_available, display_prefs = display_prefs, sort_columns = current_app.config['SORT_COLUMNS'])

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