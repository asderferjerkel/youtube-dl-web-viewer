from flask import render_template, redirect, request, session
from app import app, helpers, db, api

# Read config file when restarted
try:
	config = read_conf(config_file)
except OSError:
	# Could not access config file (doesn't exist or wrong permissions)
	logging.exception('Read error')

# If config is missing, redirect all requests to init route
@app.before_request
def check_conf():
	try:
		config
	except NameError:
		return redirect(url_for('initialise', e = 'conf'))

@app.route('/')
def index():
	# already checked conf, so
	# query db: is a login required?
	  # if required is null, db has just been created
	return 'video page!'

@app.route('/login')
def login():
	return 'login'

@app.route('/settings')
def settings():
	return 'settings'

@app.route('/init')
def initialise():
	# if GET
	  # if e = conf
	    # return .conf missing/permissions message, retry link to /init (no query)
	  # if db doesn't exist (check for file)
	    # return POST button to create (need some crsf protec)
	  # else
	    # return db already exists, delete file and refresh to recreate
	# if POST
	  # check for db again, as above if exists
	  # if doesn't, run db.create()
	  # if success, success message and link to settings
	return 'init'