from flask import Flask
import logging
import sys

def create_app():
	app = Flask(__name__)
	
	# Default config
	app.config.from_mapping(
		SECRET_KEY='dev',
		DATABASE='data.sqlite'
	)
	
	# Get user config if it exists
	app.config.from_pyfile('config.py', silent=True)
	
	# Set up basic logging
	logging.basicConfig(
		stream = sys.stderr,
		level = logging.DEBUG,
		format = '%(asctime)s %(levelname)s: %(message)s',
		datefmt = '%Y-%m-%d %H:%M:%S'
	)
	
	# Register blueprints
	# View functions must be imported in __init__.py as per https://flask.palletsprojects.com/en/1.1.x/patterns/packages/
	
	from . import db
	# Register database functions
	db.init_app(app)
	
	# Log to database if available
	app.logger.addHandler(db.LogToDB())
	
	app.register_blueprint(db.blueprint)
	
	from . import index
	app.register_blueprint(index.blueprint)
	
	from . import auth
	app.register_blueprint(auth.blueprint)
	
	from . import settings
	app.register_blueprint(settings.blueprint)
	
	return app