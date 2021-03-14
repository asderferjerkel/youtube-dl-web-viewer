from contextlib import closing
import sqlite3
import logging
from datetime import datetime

def check_exists():
	# just check file
	return

def execute(sql):
	#try:
		
	#with closing(sqlite3.connect #etc
	return

def create(filename):
	# get filename from config
	return # if success

# Extra logging on top of basicConfig
class log_to_db(logging.Handler):
	"""Custom log handler to add to the database"""
	def emit(self, record):
		log_datetime = datetime.fromtimestamp(record.created)
		log_level = str(record.levelname)
		log_message = str(record.msg)
		
		query = """INSERT INTO log (log_datetime, log_level, log_message) VALUES (%s, %s, %s)"""
		#with db.cursor

def add_db_log():
	return