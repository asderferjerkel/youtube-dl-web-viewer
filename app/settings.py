import functools

from pathlib import Path

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, BooleanField, validators

from app.auth import login_required, add_user, update_user, LoginUser, AddUser, UpdateUser, AdminUpdateUser, AdminUpdateUsers
from app.db import get_db, get_params
from app.helpers import check_conf

blueprint = Blueprint('settings', __name__, url_prefix='/settings')

# Validate settings
def is_folder(form, field):
	"""Check if the provided folder path exists"""
	if not Path(field.data).is_dir():
		# Could also be a broken symlink
		raise ValidationError('Path is not a directory or does not exist')

# Settings form
class GeneralSettings(FlaskForm):
	# Allow 0 or a non-zero integer optionally followed by s, m, h, d, w
	refresh_interval = StringField('Database refresh interval (seconds)', [validators.Optional(), validators.Regexp(u'^(?:0|[1-9]+\\d*[smhdw]?)$', message = 'Incorrect interval format')])
	disk_path = StringField('Path on disk to scan for videos', [is_folder])
	web_path = StringField('Web path that serves videos', [validators.URL(require_tld = False)])
	metadata_source = SelectField('Get video metadata from', choices = [('json', 'filename')])
	filename_format = StringField('Video filename format', [validators.Optional()])
	filename_delimiter = StringField('Video filename delimiter', [validators.Optional()])
	public_can_view = BooleanField('Enable guest access')

@blueprint.route('/firstrun', methods = ('GET', 'POST'))
def first_run():
	"""Create the first user after the database is initialised"""
	# Deny if any users registered
	try:
		users = get_db().execute('SELECT id FROM users').fetchone()
	except sqlite3.OperationalError:
		flash('Database error: could not check registered users')
		return redirect(url_for('index'))
	else:
		if users is not None:
			flash('First user already created')
			return redirect(url_for('index'))
	
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
			flash('Failed to create account')
		else:
			flash('Account created successfully')
			# Log in immediately
			session.clear()
			session['user_id'] = user_id
			return redirect(url_for('settings.general'))
	
	return render_template('settings/firstrun.html', title = 'Create admin user', form = form)

@blueprint.route('/', methods = ('GET', 'POST'))
@login_required('admin')
def general():
	"""General settings (restricted to admin users)"""
	# Warn if development keys are being used
	check_conf()
	
	# Update settings
	settings_form = GeneralSettings()
	
	if settings_form.validate_on_submit():
		# Interval string to seconds
		try:
			refresh_interval = int(settings_form.refresh_interval.data)
		except:
			units = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800}
			refresh_interval = int(settings_form.refresh_interval.data[:-1]) * units[settings_form.refresh_interval.data[-1]]
		
		# Add trailing slash to paths
		# jinja2 autoescapes in templates so web path should be safe enough (famous last words lol)
		disk_path = settings_form.disk_path.data
		web_path = settings_form.web_path.data
		if disk_path[-1] != '/':
			disk_path = disk_path + '/'
		if web_path[-1] != '/':
			web_path = web_path + '/'
		
		metadata_source = settings_form.metadata_source.data
		filename_format = settings_form.filename_format.data
		filename_delimiter = settings_form.filename_delimiter.data
		guests_can_view = 1 if settings_form.guests_can_view.data else 0
		
		db = get_db()
		try:
			db.execute('UPDATE params SET refresh_interval = ?, disk_path = ?, web_path = ?, metadata_source = ?, filename_format = ?, filename_delimiter = ?, guests_can_view = ?', (
				refresh_interval,
				disk_path,
				web_path,
				metadata_source,
				filename_format,
				filename_delimiter,
				guests_can_view
				))
		except sqlite3.OperationalError as e:
			flash('Failed to update settings: ' + str(e))
		else:
			db.commit()
			flash('Settings updated.')
	
	# Pre-fill settings from database (after update, if took place)
	try:
		params = get_params()
	except sqlite3.OperationalError as e:
		flash('Failed to get current settings: ' + str(e))
	else:
		settings_form = GeneralSettings(data = params)
		
		# Check if this is the first time saving settings
		if params['last_refreshed'] == 0:
			flash('Setup complete! Click "Refresh database" below to scan for videos for the first time.')
	
	return render_template('settings/general.html', title = 'General settings', form = form)

@blueprint.route('/user', methods = ('GET', 'POST'))
@login_required('user')
def user():
	"""User settings (users can update self, admins can update all)"""
	update_users_form = None
	add_user_form = None
	
	# Admin-only settings
	if g.user['is_admin']:
		# Warn if development keys are being used
		check_conf()
		
		# Update users
		update_users_form = AdminUpdateUsers()
		
		if update_users_form.validate_on_submit():
			try:
				for user in update_users_form.users:
					update_user(id = user.user_id.data, username = user.username.data, password = user.password.data, is_admin = user.is_admin.data, delete_user = user.delete_user.data)
			except sqlite3.OperationalError:
				flash('Database error: could not update users')
			else:
				flash('Users updated')
		
		# Pre-fill users from database (after update, if took place)
		try:
			# Exclude self
			users = get_db().execute('SELECT id, username, is_admin FROM users WHERE id != ?', g.user['id']).fetchall()
		except sqlite3.OperationalError as e:
			flash('Could not load user data: ' + str(e))
		else:
			# Only display if there are users other than self
			if len(users) > 0:
				# Create a subform for each user
				for user in users:
					user_form = AdminUpdateUser()
					user_form.user_id = user['id']
					user_form.username = user['username']
					user_form.is_admin.default = 'checked' if user['is_admin'] else ''
					
					# Append it to the parent form
					update_users_form.users.append_entry(user_form)
					
		# Add users
		add_user_form = AddUser()
		
		if add_user_form.validate_on_submit():
			username = add_user_form.username.data
			password = add_user_form.password.data
			
			add_user(username, password)
		
	# Update self
	update_self_form = UpdateUser()
	
	if update_self_form.validate_on_submit():
		current_password = update_self_form.current_password.data
		new_password = update_self_form.new_password.data
		
		if not check_password_hash(g.user['password'], current_password):
			flash('Current password is incorrect')
		else:
			try:
				update_user(id = g.user['id'], password = new_password)
			except sqlite3.OperationalError:
				flash('Database error: could not change password')
			else:
				flash('Password changed')
	
	return render_template('settings/user.html', title = 'User settings', update_users_form = update_users_form, add_user_form = add_user_form, update_self_form = update_self_form)