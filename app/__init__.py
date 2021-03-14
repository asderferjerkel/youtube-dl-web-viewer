import os
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
	logging.basicConfig(stream=sys.stderr)
	
	# View functions must be imported in __init__.py as per https://flask.palletsprojects.com/en/1.1.x/patterns/packages/
	#from app import views
	
	@app.route('/')
	def hello():
		return 'Hello, World!'
	
	return app