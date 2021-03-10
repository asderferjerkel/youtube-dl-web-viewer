from configparser import ConfigParser

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