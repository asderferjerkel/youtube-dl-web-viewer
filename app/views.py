from app import app
from app import helpers
from app import db
from app import api

# Read config file when restarted
try:
	config = helpers.read_conf('youtube-dl-web-viewer.conf')
except OSError:
	

@app.route('/')
def index():
	return 'video page!'

@app.route('/login')
def login():
	return 'login'

@app.route('/settings')
def settings():
	return 'settings'

@app.route('/init')
def initialise():
	return 'init'