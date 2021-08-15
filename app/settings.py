import functools
try:
	from pysqlite3 import dbapi2 as sqlite3
except ImportError:
	import sqlite3

from pathlib import Path
from datetime import datetime

from flask import (Blueprint, flash, g, current_app, redirect, render_template,
				   request, session, url_for)
from werkzeug.security import check_password_hash	

from flask_wtf import FlaskForm
from wtforms import (StringField, PasswordField, SelectField, BooleanField,
					 HiddenField, validators)
from wtforms.validators import ValidationError

from app.auth import (login_required, add_user, update_user, login_user,
					  LoginUser, AddUser, UpdateUser, AdminUpdateUser,
					  AdminUpdateUsers)
from app.db import get_db, get_params
from app.helpers import check_conf

try:
	from PIL import features
except ImportError:
	features = None

blueprint = Blueprint('settings', __name__, url_prefix='/settings')

# Validate settings
def is_folder(form, field):
	"""Check if the provided folder path exists"""
	if not Path(field.data).is_dir():
		# Could also be a broken symlink
		raise ValidationError('Path is not a directory or does not exist.')

# Settings form
class GeneralSettings(FlaskForm):
	# Allow 0 or a non-zero integer optionally followed by s, m, h, d, w
	refresh_interval = StringField('Database refresh interval (seconds)', [validators.Regexp(u'^(?:0|[1-9]+\\d*[smhdw]?)$', message = 'Incorrect interval format (set to 0 to disable)')])
	disk_path = StringField('Path on disk to scan for videos', [is_folder])
	web_path = StringField('Web path that serves videos', [validators.URL(require_tld = False)])
	metadata_source = BooleanField('Scan for metadata files')
	generate_thumbs = BooleanField('Generate playlist thumbnails')
	filename_format = StringField('Video filename format', [validators.Optional()])
	filename_delimiter = StringField('Video filename delimiter', [validators.Optional()])
	replace_underscores = BooleanField('Replace underscores in titles')
	guests_can_view = BooleanField('Enable guest access')


def init_app(app):
	"""Warn if image generation support is missing"""
	with app.app_context():
		if features is None:
			current_app.logger.warning('Thumbnail generation unavailable: Pillow is not installed')


@blueprint.route('/firstrun', methods = ('GET', 'POST'))
def first_run():
	"""Create the first user after the database is initialised"""
	# Deny if any users registered
	try:
		params = get_params()
	except sqlite3.OperationalError:
		# Params table missing, go to init
		return redirect(url_for('db.init'))
	else:
		if params['setup_complete'] == 1:
			flash('Setup already completed', 'warn')
			return redirect(url_for('settings.general'))
	
	# Warn if development keys are being used
	check_conf()
	
	# Create registration form for first admin user
	form = AddUser()
	
	if form.validate_on_submit():
		username = form.username.data
		password = form.password.data
		
		try:
			user_id = add_user(username, password, is_admin = 1)
		except sqlite3.OperationalError:
			flash('Failed to create account', 'error')
		else:
			# Log in immediately
			login_user(user_id)
			
			flash('Account created successfully', 'info')
			# Mark setup as complete
			db = get_db()
			try:
				db.execute('UPDATE params SET setup_complete = 1 ORDER BY rowid LIMIT 1')
			except sqlite3.OperationalError:
				flash('Could not mark setup as complete', 'error')
			else:
				db.commit()
				return redirect(url_for('settings.general'))
	
	return render_template('settings/firstrun.html', title = 'Create admin user', form = form)

@blueprint.route('/', methods = ('GET', 'POST'))
@login_required('admin')
def general():
	"""General settings (restricted to admin users)"""
	# Update settings
	settings_form = GeneralSettings()
	# Default strings
	last_refreshed = 'Never'
	next_refresh = 'Refresh database once to enable autorefresh'
	thumbnail_status = 'Unavailable: Pillow is not installed'
	
	if settings_form.validate_on_submit():
		# Interval string to seconds
		try:
			refresh_interval = int(settings_form.refresh_interval.data)
		except:
			units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}
			refresh_interval = int(settings_form.refresh_interval.data[:-1]) * units[settings_form.refresh_interval.data[-1]]
		
		# Add trailing slash to web path if not present
		# jinja2 autoescapes in templates so web path should be safe enough (famous last words lol)
		disk_path = settings_form.disk_path.data
		web_path = settings_form.web_path.data
		if web_path[-1] != '/':
			web_path = web_path + '/'
		metadata_source = 1 if settings_form.metadata_source.data else 0
		generate_thumbs = 0
		if settings_form.generate_thumbs.data:
			# Thumbnail generation enabled
			if features is not None:
				# Pillow is installed
				generate_thumbs = 1
			else:
				flash('Thumbnail generation unavailable: Pillow is not installed (see help)', 'warn')
		filename_format = settings_form.filename_format.data
		filename_delimiter = settings_form.filename_delimiter.data
		replace_underscores = 1 if settings_form.replace_underscores.data else 0
		guests_can_view = 1 if settings_form.guests_can_view.data else 0
		
		db = get_db()
		try:
			db.execute('UPDATE params SET refresh_interval = ?, disk_path = ?, web_path = ?, metadata_source = ?, generate_thumbs = ?, filename_format = ?, filename_delimiter = ?, replace_underscores = ?, guests_can_view = ?', (
				refresh_interval,
				disk_path,
				web_path,
				metadata_source,
				generate_thumbs,
				filename_format,
				filename_delimiter,
				replace_underscores,
				guests_can_view
				))
		except sqlite3.OperationalError as e:
			flash('Failed to update settings: ' + str(e), 'error')
		else:
			db.commit()
			flash('Settings updated.', 'info')
			try:
				params = get_params()
			except sqlite3.OperationalError as e:
				flash('Failed to get current settings: ' + str(e), 'error')
			else:
				# Check if this is the first time saving settings
				if params['last_refreshed'] == 0:
					flash('Setup complete! Click "Refresh database" below to scan for videos for the first time.', 'info')
			# Redirect so a refresh doesn't resubmit the form
			return redirect(url_for('settings.general'))
	
	if request.method == 'GET':
		# Warn if development keys are being used
		check_conf()
		
		# Pre-fill settings from database
		try:
			params = get_params()
		except sqlite3.OperationalError as e:
			flash('Failed to get current settings: ' + str(e), 'error')
		else:
			settings_form = GeneralSettings(data = params)
			# Get database last and next refresh
			if params['last_refreshed'] != 0:
				last_refreshed = datetime.strftime(datetime.fromtimestamp(params['last_refreshed']), '%d/%m/%Y %H:%M') + ' UTC'
				next_refresh = datetime.strftime(datetime.fromtimestamp(params['last_refreshed'] + params['refresh_interval']), '%d/%m/%Y %H:%M') + ' UTC'
		
		# Display available thumbnail formats
		if features is not None:
			# Pillow is installed
			thumbnail_status = 'Available formats: '
			thumbnail_formats = []
			if 'jpg' in features.get_supported_codecs():
				thumbnail_formats.append('jpg')
			if 'webp' in features.get_supported_modules():
				thumbnail_formats.append('webp')
			
			if len(thumbnail_formats) > 0:
				thumbnail_status += ', '.join(thumbnail_formats)
			else:
				thumbnail_status += 'None'
	
	return render_template('settings/general.html', title = 'General settings', form = settings_form, last_refreshed = last_refreshed, next_refresh = next_refresh, thumbnail_status = thumbnail_status)

@blueprint.route('/user', methods = ('GET', 'POST'))
@login_required('user')
def user():
	"""User settings (users can update self, admins can update all)"""
	update_users_form = None
	add_user_form = None
	
	# Admin-only settings
	if g.user['is_admin']:
		# Add users (before update so it can prefill with new user)
		add_user_form = AddUser()
		
		if add_user_form.add.data and add_user_form.validate():
			username = add_user_form.username.data
			password = add_user_form.password.data
			
			try:
				add_user(username, password)
			except sqlite3.OperationalError:
				flash('Database error: could not add user', 'error')
			else:
				flash('User added', 'info')
				return redirect(url_for('settings.user'))
		
		# Update users
		update_users_form = AdminUpdateUsers()
		
		# Check for submit button content before validate to allow multiple forms per page: https://stackoverflow.com/a/39766205
		if update_users_form.update_many.data and update_users_form.validate():
			try:
				for user in update_users_form.users:
					update_user(id = user.user_id.data, username = user.username.data, password = user.password.data, is_admin = user.is_admin.data, delete_user = user.delete_user.data)
			except sqlite3.OperationalError:
				flash('Database error: could not update users', 'error')
			else:
				flash('Users updated', 'info')
				return redirect(url_for('settings.user'))
		
		# Don't prefill users until form successfully validates
		# so it doesn't reset on a failed validation
		if (request.method == 'GET' or add_user_form.add.data):
			# Warn if development keys are being used
			check_conf()
			try:
				# Exclude self
				users = get_db().execute('SELECT id, username, is_admin FROM users WHERE id != ?', (g.user['id'], )).fetchall()
			except sqlite3.OperationalError as e:
				flash('Could not load user data: ' + str(e), 'warn')
			else:
				while len(update_users_form.users) > 0:
					# Clear existing entries
					update_users_form.users.pop_entry()
				# Only display if there are users other than self
				if len(users) > 0:
					# Create a subform for each user
					for user in users:
						# Insert current data as default
						update_users_form.users.append_entry({'user_id': user['id'], 'username': user['username'], 'is_admin': 'checked' if user['is_admin'] else ''})
				else:
					# Hide form entirely
					update_users_form = None
	
	# Update self
	update_self_form = UpdateUser()
	
	if update_self_form.update.data and update_self_form.validate():
		current_password = update_self_form.current_password.data
		new_password = update_self_form.new_password.data
		
		# todo: this can be a validator on UpdateUser form
		try:
			user = get_db().execute('SELECT password FROM users WHERE id = ?', (g.user['id'], )).fetchone()
		except sqlite3.OperationalError:
			flash('Database error: could not check current password', 'error')
		else:
			if user is None or not check_password_hash(user['password'], current_password):
				flash('Current password is incorrect', 'warn')
			else:
				try:
					update_user(id = g.user['id'], password = new_password)
				except sqlite3.OperationalError:
					flash('Database error: could not change password', 'error')
				else:
					flash('Password updated', 'info')
					return redirect(url_for('settings.user'))
	
	return render_template('settings/user.html', title = 'User settings', update_users_form = update_users_form, add_user_form = add_user_form, update_self_form = update_self_form)