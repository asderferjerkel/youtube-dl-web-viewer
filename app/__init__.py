import logging
import sys
import os

from flask import Flask
from flask_wtf.csrf import CSRFProtect

import datetime

def create_app():
	app = Flask(__name__, instance_relative_config = True)
	
	# Default config
	# Copy config.py-dist to instance/config.py to override
	app.config.from_mapping(
		SECRET_KEY = 'dev',
		PERMANENT_SESSION_LIFETIME = datetime.timedelta(days = 93),
		WTF_CSRF_TIME_LIMIT = None, # Expire with session
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
			'sort_title': 'Title',
			'position': 'Filename #',
			'filename': 'Filename A-Z',
			'upload_date': 'Upload date',
			'modification_time': 'Download date',
			'view_count': 'Views',
			'average_rating': 'Rating',
			'duration': 'Duration'
			},
		THUMBNAIL_FORMATS = {
			'jpg':  { 'export_format': 'JPEG',
					  'priority': 0 },
			'webp': { 'export_format': 'WEBP',
					  'priority': 1 }
			},
		THUMBNAIL_SIZE = (128, 72),
		THUMBNAIL_QUALITY = 70,
		DATABASE_LOG_LEVEL = logging.DEBUG
	)
	
	# Get user config if it exists
	app.config.from_pyfile('config.py', silent = True)
	
	# Set up basic logging
	logging.basicConfig(
		stream = sys.stderr,
		level = logging.ERROR,
		format = '%(asctime)s %(levelname)s: %(message)s',
		datefmt = '%Y-%m-%d %H:%M:%S'
	)
	
	# Create instance folder
	try:
		os.makedirs(app.instance_path)
	except OSError as e:
		print('Could not create instance folder: ' + str(e))
	
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
	# Test for image generation support
	settings.init_app(app)
	
	from . import api
	app.register_blueprint(api.blueprint)
	# Reset task on server restart
	api.init_app(app)
		
	return app