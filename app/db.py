from contextlib import closing
import sqlite3
from datetime import datetime

def check_exists():
	return

def create_empty():
	return

def cursor():
	return

def query():
	with closing(
	return

# Extra logging on top of basicConfig
class log_to_db(logging.Handler):
	"""
	Custom log handler that adds to the database
	"""
	def emit(self, record):
		log_datetime = datetime.fromtimestamp(record.created)
		log_level = str(record.levelname)
		log_message = str(record.msg)
		
		query = """INSERT INTO log (log_datetime, log_level, log_message) VALUES (%s, %s, %s)"""
		with db.cursor

def add_db_log():
	