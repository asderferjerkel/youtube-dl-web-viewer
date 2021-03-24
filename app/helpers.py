from flask import current_app, g, flash
from flask_navigation import Navigation

def init_app(app):
	nav = Navigation()
	nav.init_app(app)
	
	nav.Bar('top', [
		nav.Item('Home', 'index.index'),
		nav.Item('Settings', 'settings.general'),
		nav.Item('Users', 'settings.user'),
		nav.Item('Log', 'index.error_log')
		])

def check_conf():
	"""Warn if development secret keys are being used"""
	# todo: include flash category in template as per https://flask.palletsprojects.com/en/1.1.x/patterns/flashing/
	if current_app.config['SECRET_KEY'] == 'dev':
		flash('Development keys are in use. Your cookies are not secure! Copy config.py-dist to config.py and set SECRET_KEY to dismiss this message.')