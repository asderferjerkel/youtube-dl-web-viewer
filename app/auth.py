import functools
import json

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for, jsonify
from werkzeug.security import check_password_hash, generate_password_hash

from flask_wtf import FlaskForm
from wtforms import Form, StringField, PasswordField, BooleanField, IntegerField, HiddenField, FieldList, FormField, validators
from wtforms.validators import ValidationError

import sqlite3
from app.db import get_db, get_params

blueprint = Blueprint('auth', __name__)

# Form validation
def validate_username(form, field):
	"""Forbids existing usernames"""
	try:
		if get_db().execute('SELECT id FROM users WHERE username = ?', field.data).fetchone() is not None:
			raise ValidationError('Username already in use')
	except sqlite3.OperationalError:
		raise ValidationError('Could not check username availability')

def validate_username_update(form, field):
	"""Forbids existing usernames, ignoring current if unchanged"""
	try:
		if get_db().execute('SELECT id FROM users WHERE username = ? AND id != ?',
			(field.data, form.user_id.data)
			).fetchone() is not None:
			raise ValidationError('Username already in use')
	except sqlite3.OperationalError:
		raise ValidationError('Could not check username availability')

def protect_self(form, field):
	"""
	Forbids admins demoting or deleting their own accounts if they manually edit the ID field
	Apply to forbidden fields is_admin, delete_user
	(to delete or demote an admin account, log in as a different admin user)
	"""
	if field.data:
		# Boolean is checked
		if g.user['id'] == int(form.user_id.data):
			raise ValidationError('You cannot demote or delete yourself')

# User auth & update forms
class LoginUser(FlaskForm):
	username = StringField('Username', [validators.InputRequired()])
	password = PasswordField('Password', [validators.InputRequired()])

class AddUser(FlaskForm):
	username = StringField('Username', [validators.InputRequired(), validators.Length(min = 1, max = 255), validate_username])
	password = PasswordField('Password', [validators.Length(min = 6, max = 255)])
	repeat = PasswordField('Repeat password', [validators.EqualTo('password', message = 'Passwords do not match')])

class UpdateUser(FlaskForm):
	current_password = PasswordField('Current password', [validators.Length(min = 6, max = 255)])
	new_password = PasswordField('New password', [validators.Length(min = 6, max = 255)])
	repeat = PasswordField('Repeat password', [validators.EqualTo('new_password', message = 'Passwords do not match.')])

class AdminUpdateUser(Form):
	# Subform is Form rather than FlaskForm as CSRF field only needs including once in parent
	user_id = IntegerField(widget=HiddenField())
	username = StringField('Username', [validators.InputRequired(), validators.Length(min = 1, max = 255), validate_username_update])
	password = PasswordField('Password', [validators.Optional(), validators.Length(min = 6, max = 255)])
	# todo: set to BooleanSubField if necessary
	is_admin = BooleanField('Admin', [protect_self])
	# Defaults unchecked
	delete_user = BooleanField('Delete user', [protect_self])

class AdminUpdateUsers(FlaskForm):
	users = FieldList(FormField(AdminUpdateUser))

class BooleanSubField(BooleanField):
	"""
	Bugfix:
	https://github.com/wtforms/wtforms/issues/308#issuecomment-263014194
	https://github.com/lepture/flask-wtf/issues/362
	Replace BooleanField with BooleanSubField in subform if necessary
	"""
	def process_data(self, value):
		if isinstance(value, BooleanField):
			self.data = value.data
		else:
			self.data = bool(value)

def add_user(username, password, is_admin = 0):
	"""Add a new user. Expects a valid username and password, and the username to already be checked for collisions. Optionally set is_admin = 1 to make an admin. Returns unique user ID."""
	db = get_db()
	db.execute('INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)',
		(username, generate_password_hash(password), is_admin)
	)
	id = db.execute('SELECT last_insert_rowid() FROM users').fetchone()[0]
	db.commit()
	return id

def update_user(id, username = None, password = None, is_admin = None, delete_user = None):
	"""
	Update a user. id must be supplied, everything else is optional. Expects valid username & password. Specify is_admin = True/False to promote/demote; delete_user = True to delete.
	"""
	db = get_db()
	
	if delete_user:
		flash('Would be deleting user ' + str(username) + '(ID ' + str(id) + ')')
		#try:
			#db.execute('DELETE FROM users WHERE id = ?', id)
		#
		#db.commit()
	
	else:
		if is_admin is not None:
			# True/False to 1/0
			is_admin = 1 if is_admin else 0
		if password:
			# Don't generate a hash for empty (unchanged) or None (throws an exception) passwords
			password = generate_password_hash(password)
		
		# Update any supplied columns
		db.execute('UPDATE users SET username = COALESCE(?, username), password = COALESCE(?, password), is_admin = COALESCE(?, is_admin) WHERE id = ?',
			(username, password, is_admin, int(id))
		)
		db.commit()

@blueprint.before_app_request
def load_user():
	"""Make user info available to views if logged in"""
	user_id = session.get('user_id')
	g.user = None
	
	if user_id is not None:
		try:
			g.user = get_db().execute('SELECT id, username, is_admin FROM users WHERE id = ?', user_id).fetchone()
		except sqlite3.OperationalError:
			# Don't store in case of DB failure
			pass

@blueprint.route('/login', methods = ('GET', 'POST'))
def login():
	form = LoginUser()
	
	if g.user is not None:
		flash('Already logged in')
		return redirect(url_for('index'))
	
	# If POST request and form is valid
	if form.validate_on_submit():
		username = form.username.data
		password = form.password.data
		
		try:
			user = get_db().execute('SELECT id, password FROM users WHERE username = ?', username).fetchone()
		except sqlite3.OperationalError:
			flash('Database not initialised')
			return redirect(url_for('db.init'))
		
		if user is None or not check_password_hash(user['password'], password):
			flash('Incorrect username/password')
			return redirect(url_for('auth.login'))

		# Successful login
		session.clear()
		session['user_id'] = user['id']
		return redirect(url_for('index'))
	
	return render_template('login.html', title = 'Login', form = form)

@blueprint.route('/logout')
def logout():
	if g.user is not None:
		session.clear()
		flash('Logged out')
	else:
		flash('Not logged in')
	
	return redirect(url_for('auth.login'))

def login_required(user_class = 'user', api = False):
	"""
	Restricts a view to logged in (default) or admin users, or allows guests if specified in settings.
	Specify api = True to restrict an API endpoint (returns 403 Forbidden instead of a redirect)
	user_class = user, admin or guest
	"""
	def decorator(view):
		@functools.wraps(view)
		def wrapped_view(**kwargs):
			if g.user is not None:
				# Logged in
				if (user_class == 'guest' or
						user_class == 'user' or
						(user_class == 'admin' and g.user['is_admin'])):
					# User has correct permissions
					return view(**kwargs)
				
				# User is not an admin
				if api:
					return jsonify({'status': 'error',
									'message': 'Unauthorised'}), 403
				flash('Page is restricted to admin users.')
				return redirect(url_for('index'))
			
			# Not logged in
			try:
				params = get_params()
			except sqlite3.OperationalError as e:
				# Params table missing, go to init
				if api:
					return jsonify({'status': 'error',
									'message': 'Database error'}), 500
				return redirect(url_for('db.init'))
			
			if user_class == 'guest' and params['guests_can_view']:
				# Guests allowed
				return view(**kwargs)
			
			# Guests disallowed
			flash('You must be logged in to view this page.')
			if api:
				return jsonify({'status': 'error',
								'message': 'Unauthorised'}), 403
			return redirect(url_for('auth.login'))
		
		return wrapped_view
	return decorator