from configparser import ConfigParser

def app_start():
	# read text config
	# if missing or permissions issue, 
	return

def page_load():
	return

def log_message():
	return

def read_conf(filename):
	config = ConfigParser()
	if config.read(filename) == []:
		raise OSError(5, 'Could not read config file', filename)
	else:
		return config