import logging
import sys
import os

from flask import Flask
from flask_wtf.csrf import CSRFProtect

import datetime

def create_app():
	app = Flask(__name__, instance_relative_config = True)
	
	# Default config
	# Copy config.py-dist to config.py to override
	app.config.from_mapping(
		SECRET_KEY = 'dev',
		PERMANENT_SESSION_LIFETIME = datetime.timedelta(days = 93), # Sessions default to 3 months
		DATABASE = 'data.sqlite',
		VIDEO_EXTENSIONS = {
			'.mp4': 'video/mp4',
			'.webm': 'video/webm',
			'.mkv': 'video/x-matroska',
			'.flv': 'video/x-flv'
			},
		THUMBNAIL_EXTENSIONS = {
			'.webp': 'image/webp',
			'.avif': 'image/avif',
			'.jpg': 'image.jpeg',
			'.jpeg': 'image/jpeg',
			'.png': 'image/png',
			'.gif': 'image/gif'
			},
		METADATA_EXTENSION = '.info.json',
		SORT_COLUMNS = {
			'playlist_index': 'Playlist',
			'position': 'File #',
			'sort_title': 'Title',
			'filename': 'Filename',
			'upload_date': 'Uploaded',
			'modification_time': 'Downloaded',
			'view_count': 'Views',
			'average_rating': 'Rating',
			'duration': 'Duration'
			},
		DATABASE_LOG_LEVEL = logging.DEBUG,
		WTF_CSRF_TIME_LIMIT = None # CSRF tokens expire with session
	)
	
	# Get user config if it exists
	app.config.from_pyfile('config.py', silent = True)
	
	# Set up basic logging
	logging.basicConfig(
		stream = sys.stderr,
		level = logging.DEBUG,
		format = '%(asctime)s %(levelname)s: %(message)s',
		datefmt = '%Y-%m-%d %H:%M:%S'
	)
	
	# CSRF protection
	csrf = CSRFProtect()
	csrf.init_app(app)
	
	# Register navigation
	from . import helpers
	helpers.init_app(app)
	
	# Register blueprints
	# View functions must be imported in __init__.py as per https://flask.palletsprojects.com/en/1.1.x/patterns/packages/
	
	from . import db
	# Register database functions
	db.init_app(app)
	# Log to database if available
	db.LogToDB().setLevel(app.config['DATABASE_LOG_LEVEL'])
	app.logger.addHandler(db.LogToDB())
	app.register_blueprint(db.blueprint)
	
	from . import index
	app.register_blueprint(index.blueprint)
	
	from . import auth
	app.register_blueprint(auth.blueprint)
	
	from . import settings
	app.register_blueprint(settings.blueprint)
	
	from . import api
	app.register_blueprint(api.blueprint)
	# Reset task on server restart
	api.init_app(app)
		
	return app