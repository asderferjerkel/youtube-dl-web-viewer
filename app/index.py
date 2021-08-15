import functools
try:
	import pysqlite3 as sqlite3
except ImportError:
	import sqlite3

from flask import (Blueprint, g, current_app, flash, redirect, render_template,
				   request, session, url_for)

from flask_wtf import FlaskForm
from wtforms import SubmitField

from app.auth import login_required
from app.db import get_db, get_params, get_log, count_log, clear_log
from app.api import list_folders

blueprint = Blueprint('index', __name__)

class ClearLogForm(FlaskForm):
	submit = SubmitField('Clear error log')


@blueprint.route('/', defaults = {'item_type': None, 'item_id': None})
@blueprint.route('/<string:item_type>/<int:item_id>')
@login_required('guest')
def index(item_type, item_id):
	try:
		params = get_params()
	except sqlite3.OperationalError as e:
		flash('Failed to get params: Database error', 'error')
		current_app.logger.error('Failed to get params: ' + str(e))
	
	# Get list of playlists
	try:
		playlists = list_folders()
	except sqlite3.OperationalError as e:
		current_app.logger.error('Failed to list playlists: ' + str(e))
		flash('Failed to list playlists: Database error', 'error')
		playlists = None
	
	if len(playlists) == 0:
		playlists = None
	
	# Load item from URL on page load
	load_item = {'type': item_type, 'id': item_id}
	
	# Logged out: no API, default display prefs (no cookies: resets on refresh)
	api_available = False
	display_prefs = current_app.config['DISPLAY_PREFS']
	# Logged in: API available; display prefs from session
	if g.user is not None:
		if params['last_refreshed'] != 0:
			# Autorefresh doesn't trigger until db has been refreshed once
			api_available = True
		if 'display_prefs' in session:
			display_prefs = session['display_prefs']
	
	# Load thumbs if generation enabled
	get_thumbs = False
	if params['generate_thumbs'] == 1:
		get_thumbs = True
	
	return render_template('index.html', playlists = playlists,
						   load_item = load_item,
						   api_available = api_available,
						   display_prefs = display_prefs,
						   web_path = params['web_path'],
						   get_thumbs = get_thumbs)

@blueprint.route('/log', methods = ('GET', 'POST'), defaults = {'page': 1})
@blueprint.route('/log/<int:page>', methods = ('GET', 'POST'))
@login_required('admin')
def error_log(page):
	# Entries per page
	per_page = 50;
	log = None
	form = ClearLogForm()
	
	if form.validate_on_submit():
		try:
			clear_log()
		except sqlite3.OperationalError:
			flash('Failed to clear log: Database error', 'error')
		else:
			flash('Log cleared', 'info')
			return redirect(url_for('index.error_log'))
	
	skip_entries = (page * per_page) - per_page
	try:
		log = get_log(per_page, skip_entries)
		# Total entry count for pagination
		total_entries = count_log()
	except sqlite3.OperationalError:
		flash('Failed to load log: Database error', 'error')
		total_entries = 0
	
	# Last page for pagination
	total_pages = int(((total_entries - (total_entries % per_page)) / 
						per_page) + 1)
	
	return render_template('error_log.html', title = 'Error log', log = log,
						   form = form, page = page, last_page = total_pages)