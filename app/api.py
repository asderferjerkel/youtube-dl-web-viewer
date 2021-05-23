import functools
import json
import sqlite3
import threading

from collections import OrderedDict
from itertools import islice
from datetime import datetime, timezone

from pathlib import Path
import urllib
import re

from flask import Blueprint, g, current_app, request, session, jsonify
from flask_wtf import csrf
from wtforms.validators import ValidationError

from app.db import get_db, get_params
from app.auth import login_required
from app.helpers import format_duration

blueprint = Blueprint('api', __name__, url_prefix='/api')

# todo: deal with cancelling tasks on server stop

def init_app(app):
	"""Reset running task on server restart"""
	with app.app_context():
		try:
			set_task(status = 0)
		except sqlite3.OperationalError as e:
			# Task table could be missing if db not initialised
			current_app.logger.debug('Could not clear task status: ' + str(e))

def csrf_protect(view):
	@functools.wraps(view)
	def wrapped_view(*args, **kwargs):
		try:
			csrf.validate_csrf(request.headers.get('X-CSRFToken'))
		except ValidationError:
			return jsonify({'result': 'error',
							'message': 'CSRF error: refresh the page'}), 400
		
		return view(*args, **kwargs)
	return wrapped_view

def get_task():
	"""
	Returns the currently running task.
	status = 0 (not running), 1 (running), -1 (error)
	"""
	return get_db().execute('SELECT * FROM tasks ORDER BY rowid LIMIT 1').fetchone()

def set_task(status = 0, folder = None, of_folders = None, file = None, of_files = None, message = None):
	"""
	Set the currently running task.
	Specify status = 0 (not running, default), 1 (running), -1 (error); everything else is blanked unless supplied
	"""
	db = get_db()
	db.execute('UPDATE tasks SET status = ?, folder = ?, of_folders = ?, file = ?, of_files = ?, message = ? ORDER BY rowid LIMIT 1', (
		status,
		folder,
		of_folders,
		file,
		of_files,
		message
		))
	db.commit()

def refresh_db(rescan = False):
	"""
	Scan for new videos in a separate thread and add them to the database.
	Specify rescan = True to clear existing data and rescan all videos
	"""
	try:
		# Check for running task
		if get_task()['status'] == 1:
			raise BlockingIOError('Refresh: A task is already running')
	except sqlite3.OperationalError as e:
		raise sqlite3.OperationalError('Refresh: Could not check for running tasks') from e
	
	def run_refresh_db(rescan):
		app = current_app._get_current_object()
		with app.app_context():
			db = get_db()
			
			try:
				params = get_params()
			except sqlite3.OperationalError as e:
				raise sqlite3.OperationalError('Refresh: Could not get settings') from e
			
			if rescan:
				app.logger.debug('Full rescan, clearing tables')
				# Clear tables first
				try:
					db.execute('DELETE FROM videos')
					db.execute('DELETE FROM folders')
				except sqlite3.OperationalError as e:
					raise sqlite3.OperationalError('Refresh: Could not clear existing data') from e
				else:
					db.commit()
			
			# Set task to running
			try:
				set_task(status = 1, message = 'Initialising refresh')
			except sqlite3.OperationalError as e:
				# Must fail if can't set lock on running task
				raise sqlite3.OperationalError('Refresh: Could not lock task') from e
			
			# Compile non-alphanumeric regex for sortable title
			non_alpha = re.compile('[\W_]+', re.UNICODE)
			with_warnings = False
			new_folders = 0
			new_videos = 0
			
			# Prepare filename parsing
			filename_parsing = False
			if params['filename_format'] and params['filename_delimiter']:
				filename_format = re.findall(r'\{\w+\}', params['filename_format'])
				if len(filename_format) > 0:
					app.logger.debug('Filename format present, will try to parse for metadata')
					filename_parsing = True
					
					title_position = None
					# Is {title} present?
					if '{title}' in filename_format:
						app.logger.debug('{title} present in format, will split both sides')
						# Yes, slice format on either side to later split from left and right
						title_position = filename_format.index('{title}')
						
						before_title = filename_format[:title_position]
						after_title = filename_format[title_position + 1:]
			
			db_folders = None
			if not rescan:
				app.logger.debug('Refresh only')
				try:
					db_folders = list_folders()
				except sqlite3.OperationalError as e:
					try:
						set_task(status = -1, message = 'Database error')
					except sqlite3.OperationalError:
						app.logger.error('Refresh: Could not cancel task')
					finally:
						raise sqlite3.OperationalError('Refresh: Could not list folders from database') from e
				
				# Convert folder list to a dict of path: id
				db_folders = dict((folder['folder_path'], folder['id']) for folder in db_folders)
			
			basepath = Path(params['disk_path'])
			# Check basepath exists (in case settings haven't been updated from defaults)
			if not basepath.is_dir():
				try:
					set_task(status = -1, message = 'Disk path error')
				except sqlite3.OperationalError:
					app.logger.error('Refresh: Could not cancel task')
				finally:
					raise FileNotFoundError('Refresh: Disk path does not exist')
			
			# List folders and subfolders on disk, including root folder
			disk_folders = [subfolder for subfolder in basepath.glob('**/')]
			folder_count = len(disk_folders)
			app.logger.debug('Found folders: ' + str(disk_folders))
			
			# Scan each folder for video files
			for folder_index, folder in enumerate(disk_folders, start = 1):
				app.logger.debug('Scanning folder #' + str(folder_index) + ': "' + str(folder) + '"')
				try:
					set_task(status = 1, folder = folder_index, of_folders = folder_count, message = 'Scanning folder')
				except sqlite3.OperationalError:
					app.logger.warning('Refresh: Could not update task status')
				
				files = []
				thumbnails = []
				metadatas = []
				for file in folder.glob('*'):
					# Scan for videos
					if file.suffix in app.config['VIDEO_EXTENSIONS'].keys():
						files.append(file)
					# Scan for images as potential thumbnails
					elif file.suffix in app.config['THUMBNAIL_EXTENSIONS'].keys():
						thumbnails.append(file)
					# Scan for .info.json as potential metadata
					if params['metadata_source'] == 'json':
						# Multiple file extensions (.info.json) require suffixes, but they are greedy and eat names with dots so we check the string end instead
						if file.name.endswith(app.config['METADATA_EXTENSION']):
							metadatas.append(file)
				
				# If we found video files
				if len(files) > 0:
					app.logger.debug('Found ' + str(len(files)) + ' files')
					# Check if the folder exists in the database, if the database has folders
					# DB stores folder paths relative to basepath so use that to compare
					folder_relative = folder.relative_to(basepath)
					if not rescan and db_folders and str(folder_relative) in db_folders:
						folder_id = db_folders[str(folder_relative)]
						# Folder exists, get previously-scanned videos from database by folder ID
						try:
							db_files = list_videos(folder_id)
						except sqlite3.OperationalError as e:
							try:
								set_task(status = -1, message = 'Database error')
							except sqlite3.OperationalError:
								app.logger.error('Refresh: Could not cancel task')
							finally:
								raise sqlite3.OperationalError('Refresh: Could not list videos from database') from e
						
						# Extract a list of filenames
						db_files = [file['filename'] for file in db_files]
						
						# Remove previously-scanned videos from file list
						# DB stores filename alone so remove path to compare
						files[:] = [file for file in files if file.name not in db_files]
						
						new_video_count = len(files)
						app.logger.debug('Folder previously seen, ' + str(new_video_count) + ' new files')
						
						# Add new videos to existing folder count
						video_count = len(db_files) + new_video_count
						try:
							update_folder(folder_id, video_count)
						except sqlite3.OperationalError:
							with_warnings = True
							app.logger.warning('Refresh: Could not update video count for folder "' + str(folder) + '"')
								
					else:
						app.logger.debug('Adding new folder to database')
						# Folder does not exist or starting from scratch, add to database
						if not folder_relative.parts: # Path('.').parts == ()
							folder_name = 'Root folder'
						else:
							folder_name = folder.name
							if params['replace_underscores']:
								folder_name = folder_name.replace(' _ ', ' - ').replace('_', ' ')
						# Store path as relative to basepath
						folder_path = str(folder_relative)
						# All videos are unseen
						new_video_count = len(files)
						
						try:
							folder_id = add_folder(folder_name, str(folder_relative), new_video_count)
						except sqlite3.OperationalError:
							with_warnings = True
							app.logger.warning('Refresh: Could not add new folder "' + folder_path + '" to database, skipping')
							# Skip to next folder
							continue
						else:
							new_folders += 1
					
					# Update task with total folder and new video count
					try:
						set_task(status = 1, folder = folder_index, of_folders = folder_count, file = 0, of_files = new_video_count, message = 'Scanning for new videos')
					except sqlite3.OperationalError:
						with_warnings = True
						app.logger.warning('Refresh: Could not update task status')
					
					# Iterate through the subfolder's files
					for file_index, file in enumerate(files, start = 1):
						if file_index % 10 == 0:
							# Update task every 10 files
							try:
								set_task(status = 1, folder = folder_index, of_folders = folder_count, file = file_index, of_files = new_video_count, message = 'Scanning for new videos')
							except sqlite3.OperationalError:
								with_warnings = True
								app.logger.warning('Refresh: Could not update task status')
						
						video = {}
						# Existing or new folder ID
						video['folder_id'] = folder_id
						
						# Default to basic metadata
						video['filename'] = file.name
						# Title defaults to filename without extension
						video['title'] = file.stem
						# Optionally replace " _ " with " - " (assuming unsafe character was used as separator) then remove remaining underscores
						if params['replace_underscores']:
							video['title'] = video['title'].replace(' _ ', ' - ').replace('_', '')
						# MIME type defaults to extension mapping from config
						video['video_format'] = None
						try:
							video['video_format'] = app.config['VIDEO_EXTENSIONS'][file.suffix]
						except KeyError:
							with_warnings = True
							app.logger.warning('Refresh: Did not recognise video extension "' + file.suffix + '", add with its MIME type to config.py')
						# Modification time from file (local time)
						video['modification_time'] = datetime.fromtimestamp(file.stat().st_mtime)
						
						# Match thumbnail
						video['thumbnail'] = None
						video['thumbnail_format'] = None
						for thumb in thumbnails:
							# Match filenames without extensions
							# [thumb.stem] as list to avoid partial string matches
							# eg. 'a' in 'asd' = True, 'a' in ['asd'] = False
							if file.stem in [thumb.stem]:
								app.logger.debug('Video #' + str(file_index) + ' matched thumbnail ' + str(thumb.name))
								# Store filename without path
								video['thumbnail'] = thumb.name
								try:
									# Store MIME type
									video['thumbnail_format'] = app.config['THUMBNAIL_EXTENSIONS'][thumb.suffix]
								except KeyError:
									with_warnings = True
									app.logger.warning('Refresh: Did not recognise thumbnail extension "' + thumb.suffix + '", add with its MIME type to config.py')
						# Match metadata
						metadata = None
						for meta in metadatas:
							# Path.stem only removes final extension and Path.suffixes cannot be limited to 2 (ie. .info.json), so split once from right on full extension instead
							# Metadata stem as list as above
							if file.stem in [meta.name.rsplit(app.config['METADATA_EXTENSION'], 1)[0]]:
								app.logger.debug('Video #' + str(file_index) + ' matched metadata ' + str(meta.name))
								# Store absolute path to read later
								metadata = meta
						
						# Rest of metadata defaults to None
						video.update(dict.fromkeys(['position', 'playlist_index', 'id', 'webpage_url', 'description', 'upload_date', 'uploader', 'uploader_url', 'duration', 'view_count', 'like_count', 'dislike_count', 'average_rating', 'categories', 'tags', 'height', 'vcodec', 'fps'], None))
						
						# Parse filename format if format & delimiter params are present
						if filename_parsing:
							# dict replaces duplicates but this doesn't affect the param count e.g. if multiple {skip} are present
							filename_metadata = {}
							if title_position is not None: # (can be 0)
								# {title} present: since it may contain the delimiter, we split out the rest of the variables and keep what remains as the title
								# Split filename without extension from left, keep # of vars from before_title
								left_split = file.stem.split(params['filename_delimiter'])[:len(before_title)]
								# If format only contains {title}, skip the right split as [-0:] would return the entire list
								right_split = []
								if len(filename_format) > 1:
									# Split from right, keep # of vars from after_title
									right_split = file.stem.rsplit(params['filename_delimiter'])[-len(after_title):]
								
								if len(before_title) == len(left_split):
									for index, var in enumerate(before_title):
										filename_metadata[var] = left_split[index]
									
									# Only split right if successfully split left
									if len(after_title) == len(right_split):
										for index, var in enumerate(after_title):
											filename_metadata[var] = right_split[index]
										
										# Finally split title
										# Split off everything left of title and keep the remainder
										title_split = file.stem.split(params['filename_delimiter'], len(before_title))[-1]
										# Split off everything right of title and keep the remainder
										title_split = title_split.rsplit(params['filename_delimiter'], len(after_title))[0]
										filename_metadata['{title}'] = title_split
										
									else:
										with_warnings = True
										app.logger.warning('Refresh: Filename format does not match filename: right of {title} expected ' + str(len(after_title)) + ' variable(s), got ' + str(len(right_split)))
								else:
									with_warnings = True
									app.logger.warning('Refresh: Filename format does not match filename: left of {title} expected ' + str(len(before_title)) + ' variable(s), got ' + str(len(left_split)))
							
							else:
								# {title} not present: simple split
								left_split = file.stem.split(params['filename_delimiter'])
								
								if len(left_split) == len(filename_format):
									for index, var in enumerate(filename_format):
										filename_metadata[var] = left_split[index]
								
								else:
									with_warnings = True
									app.logger.warning('Refresh: Filename format does not match filename: expected ' + str(len(filename_format)) + ' variable(s), got ' + str(len(left_split)))
								
							# Match and validate remainder of metadata
							# Won't run on an empty list if parsing failed with/without title
							for key, value in filename_metadata.items():
								if key == '{title}':
									video['title'] = str(value)
									# Optionally replace " _ " with " - " (assuming unsafe character was used as separator) then remove remaining underscores
									if params['replace_underscores']:
										video['title'] = video['title'].replace(' _ ', ' - ').replace('_', '')
								
								elif key == '{position}':
									try:
										video['position'] = int(value)
									except ValueError:
										with_warnings = True
										app.logger.warning('Refresh: Filename variable {position} is not an integer: "' + str(value) + '"')
								
								elif key == '{id}':
									try:
										video['id'] = str(value)
									except ValueError:
										with_warnings = True
										app.logger.warning('Refresh: Filename variable {id} is not a string')
								
								elif key == '{date}':
									try:
										video['upload_date'] = datetime.strptime(str(value), '%Y%m%d')
									#if re.fullmatch(r'\d{8}', str(value)):
									#	video['upload_date'] = str(value)
									#else:
									except ValueError:
										with_warnings = True
										app.logger.warning('Refresh: Filename variable {date} is not in YYYYMMDD format: "' + str(value) + '"')
						
						# Try to parse .info.json
						if metadata:
							try:
								with open(metadata) as f:
									mj = json.loads(f.read())
							except IOError as e:
								app.logger.warning('Refresh: Could not open metadata file "' + metadata.name + '"')
							except json.JSONDecodeError as e:
								app.logger.warning('Refresh: Could not parse metadata file "' + metadata.name + '"')
							else:
								# Replace fallbacks with json keys, if they exist
								# Validate ints
								for key in ('playlist_index', 'duration', 'view_count', 'like_count', 'dislike_count', 'height'):
									try:
										video[key] = int(mj.get(key)) if mj.get(key) else video[key]
									except ValueError:
										with_warnings = True
										app.logger.warning('Refresh: Metadata field "' + str(key) + '" is not an integer: "' + str(mj.get(key)) + '"')
								
								# Validate floats
								for key in ('average_rating', 'fps'):
									try:
										video[key] = float(mj.get(key)) if mj.get(key) else video[key]
									except ValueError:
										with_warnings = True
										app.logger.warning('Refresh: Metadata field "' + str(key) + '" is not numeric: "' + str(mj.get(key)) + '"')
								
								# Validate strings
								for key in ('id', 'webpage_url', 'title', 'description', 'uploader', 'uploader_url', 'vcodec'):
									video[key] = str(mj.get(key)) if mj.get(key) else video[key]
								
								# Validate lists
								for key in ('categories', 'tags'):
									try:
										video[key] = json.dumps(mj.get(key)) if mj.get(key) else video[key]
									except TypeError:
										with_warnings = True
										app.logger.warning('Refresh: Metadata field "' + str(key) + '" is not a list: "' + str(mj.get(key)) + '"')
								
								# Validate weirdos
								# re.fullmatch() raises exception if not string so check exists and coerce first
								#if mj.get('upload_date'):
								try:
									#upload_date = str(mj.get('upload_date')) if re.fullmatch(r'\d{8}', str(mj.get('upload_date'))) else upload_date
									video['upload_date'] = datetime.strptime(str(mj.get('upload_date')), '%Y%m%d') if mj.get('upload_date') else video['upload_date']
								except ValueError:
									with_warnings = True
									app.logger.warning('Refresh: Metadata field "upload_date" is not in YYYYMMDD format: "' + str(mj.get('upload_date')) + '"')
								
								# Map extension to MIME type from config
								if mj.get('ext'):
									try:
										video['video_format'] = app.config['VIDEO_EXTENSIONS']['.' + mj.get('ext')]
									except KeyError:
										with_warnings = True
										app.logger.warning('Refresh: Metadata field "extension" unrecognised: ".' + str(mj.get('ext')) + '" (add with its MIME type to config.py)')
						
						# Strip non-alphanumeric from title for sorting
						video['sort_title'] = non_alpha.sub('', video['title'])
						
						# Add to database
						app.logger.debug('Adding video #' + str(file_index) + ': "' + str(video['title']) + '"')
						try:
							add_video(video)
						except sqlite3.OperationalError as e:
							with_warnings = True
							app.logger.warning('Refresh: Could not add video "' + video['filename'] + '" to the database: ' + str(e))
						else:
							new_videos += 1
			
			# Update last_refreshed (milliseconds since epoch in UTC)
			try:
				db.execute('UPDATE params SET last_refreshed = ?', (datetime.now().replace(tzinfo=timezone.utc).timestamp(), ))
			except sqlite3.OperationalError:
				app.logger.error('Refresh: Could not set last updated time')
			finally:
				# Task complete
				message = 'Scan completed with warnings' if with_warnings else 'Scan complete'
				app.logger.debug(message)
				stats = str(new_folders) + ' new folders, ' + str(new_videos) + ' new videos'
				app.logger.debug(stats)
				message = message + "\n" + stats
				try:
					set_task(status = 0, message = message)
				except sqlite3.OperationalError:
					app.logger.error('Refresh: Could not set task to completed')
	
	threading.Thread(target = run_refresh_db(rescan)).start()

def add_folder(folder_name, folder_path, video_count):
	"""
	Add a new folder to the database.
	folder_path is relative to params['disk_path']
	"""
	db = get_db()
	db.execute('INSERT INTO folders (folder_name, folder_path, video_count) VALUES (?, ?, ?)', (
		folder_name,
		folder_path,
		video_count
		))
	id = db.execute('SELECT last_insert_rowid() FROM folders').fetchone()[0]
	db.commit()
	return id

def update_folder(id, video_count):
	"""Update the number of videos in a folder by its ID"""
	db = get_db()
	db.execute('UPDATE folders SET video_count = ? WHERE id = ?', (video_count, id))
	db.commit()

def add_video(video):
	"""
	Add a video to the database.
	Supply a dict of parameters, all but folder_id and filename can be None
	"""
	db = get_db()
	db.execute('INSERT INTO videos (folder_id, filename, thumbnail, position, playlist_index, video_id, video_url, title, sort_title, description, upload_date, modification_time, uploader, uploader_url, duration, view_count, like_count, dislike_count, average_rating, categories, tags, height, vcodec, video_format, fps) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (
		video['folder_id'],
		video['filename'],
		video['thumbnail'],
		video['position'],
		video['playlist_index'],
		video['id'],
		video['webpage_url'],
		video['title'],
		video['sort_title'],
		video['description'],
		video['upload_date'],
		video['modification_time'],
		video['uploader'],
		video['uploader_url'],
		video['duration'],
		video['view_count'],
		video['like_count'],
		video['dislike_count'],
		video['average_rating'],
		video['categories'],
		video['tags'],
		video['height'],
		video['vcodec'],
		video['video_format'],
		video['fps']
		))
	db.commit()

def list_folders():
	"""
	Returns a list of folders with their ID, name, path and video count
	Sorts by folder path for tree then name order
	"""
	return get_db().execute('SELECT * FROM folders ORDER BY folder_path ASC').fetchall()

def list_videos(folder_id, sort_by = 'playlist_index', sort_direction = 'desc'):
	"""Returns a sorted list of videos by folder ID"""
	try:
		folder_id = int(folder_id)
	except ValueError as e:
		raise ValueError('folder_id not an integer') from e
	
	if sort_by not in current_app.config['SORT_COLUMNS'].keys():
		raise ValueError('Column not allowed for sorting')
	
	if sort_direction == 'asc':
		direction_string = ' ASC'
	elif sort_direction == 'desc':
		direction_string = ' DESC'
	else:
		raise ValueError('Sort direction must be "asc" or "desc"')
	
	sort_string = ' ORDER BY videos.' + sort_by + direction_string
	if sort_by not in ['playlist_index', 'position', 'title']:
		# Secondary sorts for all but the above in case of dupe/missing values
		sort_string += (', videos.playlist_index' + direction_string +
					    ', videos.position' + direction_string)
	# All sorts finally fall back to ID 
	sort_string += ', videos.id' + direction_string
	
	return get_db().execute('SELECT videos.id, videos.title, videos.thumbnail, videos.duration, videos.filename, folders.folder_path FROM videos INNER JOIN folders ON videos.folder_id = folders.id WHERE folder_id = ?' + sort_string, (folder_id, )).fetchall()

def get_video(id):
	"""Return a single video"""
	try:
		id = int(id)
	except ValueError as e:
		raise ValueError('id not an integer') from e
	
	return get_db().execute('SELECT videos.folder_id, videos.id, videos.filename, videos.thumbnail, videos.video_id, videos.video_url, videos.title, videos.description, strftime("%d/%m/%Y", videos.upload_date) AS upload_date, strftime("%d/%m/%Y %H:%M", videos.modification_time) AS modification_time, videos.uploader, videos.uploader_url, videos.duration, videos.view_count, videos.like_count, videos.dislike_count, videos.average_rating, videos.categories, videos.tags, videos.height, videos.vcodec, videos.video_format, videos.fps, folders.folder_path, folders.folder_name FROM videos INNER JOIN folders ON videos.folder_id = folders.id WHERE videos.id = ?', (id, )).fetchone()

@blueprint.route('/refresh')
@login_required('user', api = True)
# CSRF protect refresh/rescan as only realistically DOSable endpoint
@csrf_protect
def refresh():
	"""Scan only new files for videos"""
	try:
		refresh_db()
	except (BlockingIOError, sqlite3.OperationalError) as e: # todo: also add thread error
		current_app.logger.error('Failed to start refresh: ' + str(e))
		return jsonify({'result': 'error',
						'message': str(e)}), 500
	
	return jsonify({'result': 'ok'})

@blueprint.route('/rescan')
@login_required('admin', api = True)
@csrf_protect
def rescan():
	"""Clear existing data and rescan all files for videos (restricted to admin users)"""
	try:
		refresh_db(rescan = True)
	except (BlockingIOError, sqlite3.OperationalError) as e: # todo: also add thread error
		current_app.logger.error('Failed to start rescan: ' + str(e))
		return jsonify({'result': 'error',
						'message': str(e)}), 500

	return jsonify({'result': 'ok'})

@blueprint.route('/status')
@login_required('user', api = True)
def status():
	"""Check the status of the currently-running task"""
	try:
		task = get_task()
		params = get_params()
	except sqlite3.OperationalError as e:
		current_app.logger.error('Failed to get status: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Failed to get status'}), 500
	
	# Convert sqlite3.Row object to dict for json
	task = {key: task[key] for key in task.keys()}
	
	# Calculate next database refresh
	refresh_due = False
	time_now = datetime.now().replace(tzinfo=timezone.utc).timestamp()
	next_refresh = params['last_refreshed'] + params['refresh_interval']
	if next_refresh < time_now:
		refresh_due = True
	
	return jsonify({'result': 'ok',
					'refresh_due': refresh_due,
					'data': task})

@blueprint.route('/dismiss')
@login_required('user', api = True)
def dismiss():
	"""
	Dismiss the last error from appearing in the UI
	Note: currently dismisses for all users
	"""
	try:
		set_task(status = 0)
	except sqlite3.OperationalError as e:
		current_app.logger.error('Failed to dismiss error: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Failed to dismiss error'}), 500
	
	return jsonify({'result': 'ok'})

@blueprint.route('/prefs/<string:pref>/<string:value>')
@login_required('user', api = True)
def set_preference(pref, value):
	"""Save a display preference in the logged-in user's session"""
	allowed_prefs = {'autoplay': ['0', '1'],
					 'shuffle': ['0', '1'],
					 'sort_by': current_app.config['SORT_COLUMNS'],
					 'sort_direction': ['asc', 'desc']}
	
	if pref in allowed_prefs:
		if value in allowed_prefs[pref]:
			if (pref in ['autoplay', 'shuffle']):
				subs = {'0': False, '1': True}
				value = subs[value]
			if 'display_prefs' not in session:
				return jsonify({'status': 'error',
								'message': 'Preferences missing from session, log out and in again'}), 500
		else:
			return jsonify({'status': 'error',
							'message': 'Unknown value for preference'}), 500
	else:
		return jsonify({'status': 'error',
						'message': 'Unknown preference'}), 500
	
	session['display_prefs'][pref] = value
	return jsonify({'result': 'ok',
					'message': 'Display preferences updated',
					'display_prefs': session['display_prefs']})

@blueprint.route('/playlists')
@login_required('guest', api = True)
def playlists():
	"""List playlist IDs, names and video counts"""
	try:
		folders = list_folders()
	except sqlite3.OperationalError as e:
		current_app.logger.error('Failed to list playlists: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Failed to list playlists'}), 500
	
	if len(folders) == 0:
		current_app.logger.info('No playlists in database')
		return jsonify({'result': 'error',
						'message': 'No playlists'}), 404
	
	# Convert list of sqlite3.Row objects to dict of dicts indexed by order
	# added to DB, removing folder path
	folders = {index: {key: row[key] for key in row.keys() if key != 'folder_path'} for index, row in enumerate(folders)}
	
	return jsonify({'result': 'ok',
					'data': folders})

@blueprint.route('/playlist/<int:folder_id>', defaults = {
				 'sort_by': 'playlist_index', 'sort_direction': 'desc'})
@blueprint.route('/playlist/<int:folder_id>/<string:sort_by>/<string:sort_direction>')
@login_required('guest', api = True)
def playlist(folder_id, sort_by, sort_direction):
	"""List videos in a playlist"""
	try:
		params = get_params()
	except sqlite3.OperationalError as e:
		current_app.logger.error('Failed to get params: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Failed to get params'})
	
	try:
		videos = list_videos(folder_id, sort_by, sort_direction)
	except sqlite3.OperationalError as e:
		current_app.logger.error('Failed to get playlist: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Failed to list videos'}), 500
	except TypeError as e:
		current_app.logger.info('Failed to get playlist: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Playlist does not exist'}), 404
	
	if len(videos) == 0:
		current_app.logger.info('No playlist returned')
		return jsonify({'result': 'error',
						'message': 'Playlist does not exist'}), 404
	
	# Convert list of sqlite3.Row objects to dict of dicts indexed by sort order
	videos = {index: {key: row[key] for key in row.keys()} for index, row in enumerate(videos)}
	
	for video in videos.values():
		# Format duration
		if video['duration'] is not None:
			video['duration'] = format_duration(video['duration'])
		# Generate thumbnail URL (escape spaces, HTML chars in directory and filename)
		if video['thumbnail'] is not None:
			video['thumbnail'] = params['web_path']+ urllib.parse.quote(Path(video['folder_path']).joinpath(Path(video['thumbnail'])).as_posix())
		# Remove filename, folder path
		del(video['filename'], video['folder_path'])
	
	return jsonify({'result': 'ok',
					'data': videos})

@blueprint.route('/video/<int:video_id>')
@login_required('guest', api = True)
def video(video_id):
	"""Get a single video with its web path and metadata"""
	try:
		params = get_params()
	except sqlite3.OperationalError as e:
		current_app.logger.error('Failed to get params: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Failed to get params'})
	
	try:
		video = get_video(video_id)
	except sqlite3.OperationalError as e:
		current_app.logger.error('Failed to get video: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Failed to get video'}), 500
	except TypeError as e:
		current_app.logger.info('Failed to get video: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Video does not exist'}), 404
	
	if video is None:
		current_app.logger.info('No video returned')
		return jsonify({'result': 'error',
						'message': 'Video does not exist'}), 404
	
	# Convert sqlite3.Row object to dict for json
	video = {key: video[key] for key in video.keys()}
	
	# Generate URLs for video file and thumbnail
	video['path'] = params['web_path'] + urllib.parse.quote(Path(video['folder_path']).joinpath(Path(video['filename'])).as_posix())
	if video['thumbnail']:
		video['thumbnail'] = params['web_path'] + urllib.parse.quote(Path(video['folder_path']).joinpath(Path(video['thumbnail'])).as_posix())
	# Remove unnecessary fields
	del video['filename'], video['folder_path']
	# Format duration
	if video['duration'] is not None:
		video['duration'] = format_duration(video['duration'])
	# Convert strings back to json
	for key in ('categories', 'tags'):
		if video[key]:
			try:
				video[key] = json.loads(video[key])
			except TypeError:
				# Return none if empty list
				pass

	# todo:
	# maybe move the dict stuff (same w playlists) + file_path to get_video so can grab on page load too
	  # only remove extra unneeded keys here
	# rmb thumb urls for /playlist
	# format upload_date (YYYYMMDD), modification_time (timestamp), duration
	
	return jsonify({'result': 'ok',
					'data': video})