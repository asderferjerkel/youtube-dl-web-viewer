import os
import sqlite3

import click
from flask import current_app, g
from flask.cli import with_appcontext

import logging
from datetime import datetime

import functools

from flask import (Blueprint, flash, redirect, render_template, request,
				   session, url_for)

from flask_wtf import FlaskForm
from wtforms import SubmitField

from app.helpers import check_conf

blueprint = Blueprint('db', __name__)

class LogToDB(logging.Handler):
	"""
	Custom handler to log to the database
	Since we use an app factory, use current_app.logger.info('asdf')
	(app.logger for threads) instead of logging.info('asdf')
	"""
	def __init__(self):
		logging.Handler.__init__(self)
	
	def emit(self, record):
		timestamp = datetime.fromtimestamp(record.created)
		level = str(record.levelname)
		message = str(record.msg)
		
		db = get_db()
		try:
			db.execute('INSERT INTO error_log (timestamp, level, message) '
					   'VALUES (?, ?, ?)', (timestamp, level, message))
		except sqlite3.OperationalError as e:
			print(f'Failed to log to database: {message} ({e})')
		else:
			db.commit()

class InitForm(FlaskForm):
	submit = SubmitField('Initialise database')


def init_app(app):
	"""
	Close the database connection after returning the response,
	and allow creating the database from the CLI
	"""
	app.teardown_appcontext(close_db)
	app.cli.add_command(create_db_command)

def get_db():
	"""
	Connect to the database (if not in the current request context)
	Creates the database file if it doesn't exist
	"""
	if 'db' not in g:
		# Get types from columns
		g.db = sqlite3.connect(os.path.join(current_app.instance_path, 
											current_app.config['DATABASE']),
							   detect_types = sqlite3.PARSE_DECLTYPES)
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

def column_exists(table, column):
	"""Returns True if both the provided table and column exist"""
	query = 'SELECT COUNT(*) FROM pragma_table_info( ? ) WHERE name = ?'
	col_count = get_db().execute(query, (table, column)).fetchone()[0]
	return col_count == 1

def clear_log():
	"""Clear the error log"""
	db = get_db()
	db.execute('DELETE from error_log')
	db.commit()

def get_log(limit = 50, offset = 0):
	"""
	List logged errors, starting from most recent
	Returns {limit} rows, skipping {offset} rows
	"""
	query = 'SELECT * FROM error_log ORDER BY rowid DESC LIMIT ? OFFSET ?'
	return get_db().execute(query, (limit, offset)).fetchall()

def count_log():
	"""Return int total count of logged errors"""
	return get_db().execute(
		   'SELECT COUNT (*) AS c FROM error_log').fetchone()['c']

def get_params():
	"""Retrieve settings from the database"""
	query = 'SELECT * FROM params ORDER BY rowid LIMIT 1'
	params = get_db().execute(query).fetchone()
	if params is None:
		raise sqlite3.OperationalError('params table is empty')
	return params


@click.command('create-db')
@with_appcontext
def create_db_command():
	"""
	Optionally initialise the database from the command line
	with flask create-db
	"""
	try:
		create_db()
	except FileNotFoundError as err:
		click.echo(f'Database schema not found: {err.filename}', err = True)
	except PermissionError as err:
		click.echo(f'Could not access database file: {err.filename}',
				   err = True)
	else:
		click.echo('Database created.')
	
@blueprint.route('/init', methods = ('GET', 'POST'))
def init():
	form = InitForm()
	message = None
	
	if g.user is not None:
		# Logged in, allow if admin
		if not g.user['is_admin']:
			flash('Only admin users can recreate the database', 'warn')
			return redirect(url_for('index.index'))
		message = ('Detected an existing database. Initialising will clear '
				   'all data including users and settings, but will not '
				   'remove video files. Are you sure?')
	
	else:
		# Not logged in, allow if tables missing
		try:
			params = get_params()
		except sqlite3.OperationalError:
			# Table missing, continue
			pass
		else:
			if params['setup_complete'] == 0:
				flash('Setup incomplete: Create a user first.', 'warn')
				return redirect(url_for('settings.first_run'))
			flash('Database already exists. Log in as an admin user or '
				  'manually delete the database file to proceed.', 'warn')
			return redirect(url_for('auth.login'))
		message = 'Creating a blank database.'
	
	if form.validate_on_submit():
		# POST request and form is valid
		try:
			create_db()
		except FileNotFoundError as err:
			flash(f'Database schema not found: {err.filename}', 'error')
		except PermissionError as err:
			flash(f'Could not access database file: {err.filename}', 'error')
		else:
			flash('Database successfully initialised. You may now create '
				  'an admin account.', 'info')
			return redirect(url_for('settings.first_run'))
	
	# Warn if development keys are being used
	check_conf()
	
	return render_template('init.html', title = 'Create database',
						   form = form, message = message)