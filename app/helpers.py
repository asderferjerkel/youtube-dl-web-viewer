from flask import current_app, g, flash

from flask_navigation import Navigation

def init_app(app):
	nav = Navigation()
	nav.init_app(app)
	
	nav.Bar('top', [
		nav.Item('settings', 'settings.general'),
		nav.Item('users', 'settings.user'),
		nav.Item('log', 'index.error_log')
		])

def check_conf():
	"""Warn if development secret keys are being used"""
	# todo: include flash category in template as per https://flask.palletsprojects.com/en/1.1.x/patterns/flashing/
	if current_app.config['SECRET_KEY'] == 'dev':
		flash('Development keys are in use. Your cookies are not secure! Copy config.py-dist to config.py and set SECRET_KEY to dismiss this message.', 'warn')

def format_duration(seconds):
	"""Converts int seconds to a DD:HH:MM:SS / HH:MM:SS / MM:SS / 0:SS-style duration, without leading zeroes"""
	try:
		int(seconds)
	except ValueError:
		return seconds
	minutes, seconds = divmod(seconds, 60)
	hours, minutes = divmod(minutes, 60)
	days, hours = divmod(hours, 24)
	if days > 0:
		return f'{days:d}:{hours:02d}:{minutes:02d}:{seconds:02d}'
	elif hours > 0:
		return f'{hours:d}:{minutes:02d}:{seconds:02d}'
	elif minutes > 0:
		return f'{minutes:d}:{seconds:02d}'
	else:
		return f'0:{seconds:02d}'