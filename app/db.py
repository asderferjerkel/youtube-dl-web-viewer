import sqlite3

import click
from flask import current_app, g
from flask.cli import with_appcontext

import logging
from datetime import datetime

import functools

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from flask_wtf import FlaskForm
from wtforms import SubmitField

from app.helpers import check_conf

blueprint = Blueprint('db', __name__)

def init_app(app):
	"""Close the database connection after returning the response, and allow creating the database from the CLI"""
	app.teardown_appcontext(close_db)
	app.cli.add_command(create_db_command)

def get_db():
	"""Connect to the database, if not in the current request context. Creates the database file if it doesn't exist."""
	if 'db' not in g:
		# Get types from columns
		g.db = sqlite3.connect(current_app.config['DATABASE'], detect_types = sqlite3.PARSE_DECLTYPES)
		# Return rows as dicts
		g.db.row_factory = sqlite3.Row
	return g.db

def close_db(e = None):
	"""Close the database connections if they exist"""
	db = g.pop('db', None)
	if db is not None:
		db.close()

def create_db():
	"""Clear any existing data and create empty tables"""
	with current_app.open_resource('create_db.sql') as file:
		get_db().executescript(file.read().decode('utf8'))
	get_db().commit()

@click.command('create-db')
@with_appcontext
def create_db_command():
	"""Optionally initialise the database from the command line with flask create-db"""
	try:
		create_db()
	except FileNotFoundError as err:
		click.echo('Database schema not found: ' + str(err.filename), err = True)
	except PermissionError as err:
		click.echo('Could not access database file: ' + str(err.filename), err = True)
	else:
		click.echo('Database created.')

class LogToDB(logging.Handler):
	"""Custom handler to log to the database"""
	def __init__(self):
		logging.Handler.__init__(self)
	
	def emit(self, record):
		timestamp = datetime.fromtimestamp(record.created)
		level = str(record.levelname)
		message = str(record.msg)
		
		db = get_db()
		try:
			db.execute('INSERT INTO error_log (timestamp, level, message) VALUES (?, ?, ?)',
				(timestamp, level, message)
				)
		
		except sqlite3.OperationalError as e:
			print('Failed to log to database: ' + message + ' (' + str(e) + ')')
		else:
			db.commit()

def clear_log():
	"""Clear the error log"""
	get_db().execute('DELETE from error_log')

def get_log():
	"""List logged errors"""
	# todo: limit, start_at
	return get_db().execute('SELECT * FROM error_log ORDER BY rowid DESC').fetchall()

def get_params():
	"""Retrieve settings from the database"""
	params = get_db().execute('SELECT * FROM params ORDER BY rowid LIMIT 1').fetchone()
	if params is None:
		raise sqlite3.OperationalError('params table is empty')
	else:
		return params

class InitForm(FlaskForm):
	submit = SubmitField('Initialise database')

@blueprint.route('/init', methods=('GET', 'POST'))
def init():
	form = InitForm()
	message = None
	
	if g.user is not None:
		# Logged in, allow if admin
		if not g.user['is_admin']:
			flash('Only admin users can recreate the database')
			return redirect(url_for('index.index'))
		
		message = 'Detected an existing database. Initialising will clear all data including users and settings, but will not remove video files. Are you sure?'
	
	else:
		# Not logged in, allow if tables missing
		try:
			params = get_params()
		except sqlite3.OperationalError:
			# Table missing, continue
			pass
		else:
			if params['setup_complete'] == 0:
				flash('Setup incomplete, create a user first')
				return redirect(url_for('settings.first_run'))
			
			flash('Database already exists. Log in as an admin user or manually delete the database file to proceed.')
			return redirect(url_for('auth.login'))
		
		message = 'Creating a blank database.'
	
	# If POST request and form is valid
	if form.validate_on_submit():
		try:
			create_db()
		except FileNotFoundError as err:
			flash('Database schema not found: ' + str(err.filename))
		except PermissionError as err:
			flash('Could not access database file: ' + str(err.filename))
		else:
			flash('Database successfully initialised. You may now create an admin account.')
			return redirect(url_for('settings.first_run'))
	
	# Warn if development keys are being used
	check_conf()
	return render_template('init.html', title = 'Create database', form = form, message = message)