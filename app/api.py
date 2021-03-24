import functools
import json
import sqlite3
import threading

from collections import OrderedDict
from itertools import islice

from pathlib import Path
from urllib.request import pathname2url

from flask import Blueprint, g, request, session, jsonify

from app.db import get_db, get_params
from app.auth import login_required

# one function for refresh/rescan, specify task = rescan (default refresh)
# if refresh, on check filename, match to db and skip (for each folder get filename list from db?)
# if rescan, delete from folders, videos tables

# current_task() returns running, complete or error
# get on page load
# if running, refresh every 3 secs until complete/error
# if complete, fade after 10 secs then dismiss()
# if error, click to ajax dismiss (dismiss() to clear task table and fade element)
# use json 'message': for msg (also used by login_required, along with 403 (unauth) and 500 (broken)

blueprint = Blueprint('api', __name__, url_prefix='/api')

# todo: deal with cancelling tasks on server stop

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
	# Check for running task
	try:
		if get_task()['status'] == 1:
			raise BlockingIOError('Refresh: A task is already running')
	except sqlite3.OperationalError as e:
		raise sqlite3.OperationalError('Refresh: Could not check for running tasks') from e
	
	def run_refresh_db(rescan):
		app = current_app._get_current_object()
		with app.app_context():
			db = get_db()
			
			# Get params
			try:
				params = get_params()
			except sqlite3.OperationalError as e:
				raise sqlite3.OperationalError('Refresh: Could not get settings') from e
			
			if rescan:
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
			
			# if any fatal errors, update task status = -1, current folder/video, message
			# with_warnings = False (if any warnings, set True)
			with_warnings = False
			
			# Prepare filename parsing
			filename_parsing = False
			if params['filename_format'] and params['filename_delimiter']:
				filename_format = re.findall(r'\{\w+\}', params['filename_format'])
				if len(filename_format) > 0:
					filename_parsing = True
					# Format contains variables, add position indices as values
					#filename_format = OrderedDict((var, index) for index, var in enumerate(filename_format))
					
					title_position = None
					# Is {title} present?
					if '{title}' in filename_format:
						# Yes, slice format on either side to later split from left and right
						#title_position = filename_format['{title}']
						title_position = filename_format.index('{title}')
						
						#before_title = OrderedDict(islice(filename_format.items(), 0, title_position))
						#after_title = OrderedDict(islice(filename_format.items(), title_position + 1, len(filename_format)))
						before_title = filename_format[:title_position]
						after_title = filename_format[title_position + 1:]
						
				# extract variable order to ordereddict 'x': None etc, count
				# if title present
					# split list to before_title, title, after_title
					# split from left by delimiter, times to split = len(before_title)
						# log error if necessary
						# match variable to split #
					# split from right by delimiter, times to split = len(after_title)
						# log error if necessary
						# match variable (backwards) to split #
					# for title, split from left skipping len(before_title)
					# then split again from right skilling len(after_title)
					# match title to remainder
						# log error if necessary
					# if any errors, don't bother setting title + others, just leave title as filename
				# else
					# split from left
					# match to variables
			
			# if not rescan
			db_folders = None
			if not rescan:
				try:
					# list folders from db
					db_folders = list_folders()
				except sqlite3.OperationalError as e:
					set_task(status = -1, message = 'Database error')
					raise sqlite3.OperationalError('Refresh: Could not list folders from database') from e
				
				# Convert folder list to a dict of path: id
				db_folders = dict((folder['folder_path'], folder['id']) for folder in db_folders)
			
			basepath = Path(params['disk_path'])
			# List folders and subfolders on disk, including root folder
			disk_folders = [subfolder for subfolder in basepath.glob('**/')]
			folder_count = len(disk_folders)
			
			# for each folder
				# ...
				# list videos on disk (get extensions from app.config)
				# if videos
					# if not rescan
						# match folder on disk to folder from db
						# if match
							# list videos from db by folder id
							# for each video on disk
								# match to video filename from db
								# if match
									# remove video on disk from list to check
						# if no match
							# add folder to db (rmb to check trailing /) with video count
							# (check .as_posix() for string and concat with basepath)
					# set video count (to check) = length of file list
			
			# Scan each folder for video files
			for folder_index, folder in enumerate(disk_folders, start = 1):
				try:
					set_task(status = 1, folder = folder_index, of_folders = folder_count, message = 'Scanning folders')
				except sqlite3.OperationalError:
					logging.warning('Refresh: Could not update task status')
				
				files = []
				thumbnails = []
				metadatas = []
				for file in folder.glob('*'):
					# Scan for videos
					if file.suffix in app.config['VIDEO_EXTENSIONS'].keys():
						files.add(file)
					# Scan for images as potential thumbnails
					if file.suffix in app.config['THUMBNAIL_EXTENSIONS']:
						thumbnails.add(file)
					# Scan for .info.json as potential metadata
					if params['metadata_source'] == 'json'
						# Join suffixes to check both .info and .json
						if ''.join(file.suffixes) in app.config['METADATA_EXTENSION']:
							metadatas.add(file)
				
				# If we found video files
				if len(files) > 0:
					# Check if the folder exists in the database
					if not rescan and str(folder) in db_folders:
						# Folder exists, get previously-scanned videos from database by folder id
						try:
							db_files = list_videos(db_folders[str(folder)])
						except sqlite3.OperationalError as e:
							set_task(status = -1, message = 'Database error')
							raise sqlite3.OperationalError('Refresh: Could not list videos from database') from e
						
						# Extract a list of filenames
						db_files = [file['filename'] for file in db_files]
						
						# Remove previously-scanned videos from file list
						for file in files:
							if str(file) in db_files:
								files.remove(file)
						
						new_video_count = len(files)
						
						# Update database with new video count
						video_count = len(db_files) + new_video_count
						try:
							update_folder(db_folders[str(folder)], video_count)
						except sqlite3.OperationalError:
							with_warnings = True
							logging.warning('Refresh: Could not update video count for folder "' + str(folder) + '"')
								
					else:
						# Folder does not exist or starting from scratch, add to database
						folder_name = folder.name.replace('_', ' ')
						folder_name = 'Root folder' if folder_name == '' else folder_name
						
						folder_path = str(folder)
						# Add trailing / if necessary
						#if folder_path[-1] != '/':
						#	folder_path = folder_path + '/'
						
						# Convert \\ to / and escape to form URL
						web_path = pathname2url(folder.as_posix())
						# Add trailing / if necessary
						if web_path[-1] != '/' and web_path != '':
							web_path = web_path + '/'
						
						new_video_count = len(files)
						
						try:
							add_folder(folder_name = folder_name, folder_path = folder_path, web_path = web_path, video_count = new_video_count)
						except sqlite3.OperationalError:
							with_warnings = True
							logging.warning('Refresh: Could not add new folder "' + folder_path + '" to database, skipping')
							# Skip to next folder
							continue
					
					# set task folder x of <nochange>
					# set task video 0 of x
					try:
						set_task(status = 1, folder = folder_index, of_folders = folder_count, file = 0, of_files = new_video_count, message = 'Scanning for new videos')
					except sqlite3.OperationalError:
						with_warnings = True
						logging.warning('Refresh: Could not update task status')
					
					# now we have folder and files (list) to iterate through
			
					# for each video in file list
					for file_index, file in enumerate(files, start = 1):
						if file_index % 10 == 0:
							# Update task every 10 files
							try:
								set_task(status = 1, folder = folder_index, of_folders = folder_count, file = file_index, of_files = new_video_count)
							except sqlite3.OperationalError:
								with_warnings = True
								logging.warning('Refresh: Could not update task status')
						
						# Fallback to basic metadata
						filename = file.name
						# Title defaults to filename without extension (replacing underscores)
						title = file.stem.replace('_', ' ')
						# MIME type defaults to extension mapping
						try:
							video_format = app.config['VIDEO_EXTENSIONS'][file.suffix]
						except KeyError:
							video_format = None
							with_warnings = True
							logging.warning('Refresh: Did not recognise extension "' + file.suffix + '", add with its MIME type to config.py')
						# Modification time defaults to file modification time
						modification_time = file.stat().st_mtime
						
						# Match thumbnail
						thumbnail = None
						for thumb in thumbnails:
							if file.stem in thumb.name:
								thumbnail = thumb
						# Match metadata
						metadata = None
						for meta in metadatas:
							if file.stem in meta.name:
								metadata = meta
						
						# Default rest to None
						position, playlist_index, video_id, video_url, description, upload_date, uploader, uploader_url, duration, view_count, like_count, dislike_count, average_rating, categories, tags, height, vcodec, fps = None
						
						# Can we parse the filename?
						if filename_parsing:
							# Is {title} present?
							if title_position:
								# Split from left, keep count of vars in before_title
								left_split = filename.split(params['filename_delimiter'])[:len(before_title)]
								# Split from right, keep count of vars in after_title
								right_split = filename.rsplit(params['filename_delimiter'])[-len(after_title):]
								
								filename_metadata = {}
								if len(before_title) == len(left_split):
									for index, var in enumerate(before_title):
										filename_metadata[var] = left_split[index]
									
									# Only split right if successfully split left
									if len(after_title) == len(right_split):
										for index, var in enumerate(after_title):
											filename_metadata[var] = right_split[index]
										
										# Only split title if successfully split both
										# Split off everything to the left of the title and keep the remainder
										title_split = filename.split(params['filename_delimiter'], len(before_title))[-1]
										# Split off everything to the right of the title and keep the remainder
										title_split = title_split.rsplit(params['filename_delimiter'], len(after_title))[0]
										# Remove underscores
										title = title_split.replace('_', ' ')
									
									else:
										with_warnings = True
										logging.warning('Refresh: filename format does not match filename (left of {title} expected ' + str(len(before_title)) + ' variable(s), got ' + str(len(left_split)))
								
								else:
									with_warnings = True
									logging.warning('Refresh: filename format does not match filename (left of {title} expected ' + str(len(before_title)) + ' variable(s), got ' + str(len(left_split)))
								
							else:
								# split from left
						
						# Can we parse the info.json?
						if metadata:
							# try open, read, parse
						
						# Add to database
						try:
							add_video(folder_id, filename, thumbnail, position, playlist_index, video_id, video_url, title, description, upload_date, modification_time, uploader, uploader_url, duration, view_count, like_count, dislike_count, average_rating, categories, tags, height, vcodec, video_format, fps)
						except sqlite3.OperationalError:
							with_warnings = True
							logging.warning('Refresh: Could not add video "' + filename + '" to the database')
			
			# Task complete
			message = 'Scan completed with warnings' if with_warnings else 'Scan complete'
			try:
				set_task(status = 0, message = message)
			except sqlite3.OperationalError:
				logging.warning('Refresh: Could not set task to completed')
						
						# todo: move this outside loop:
						# if filename_format and filename_delimiter (ie want to parse filename)
							# if title_position
								# split from left by delimiter, times to split = len(before_title)
									# log error if necessary
									# match variable to split #
								# split from right by delimiter, times to split = len(after_title)
									# log error if necessary
									# match variable (backwards) to split #
								# for title, split from left skipping len(before_title)
								# then split again from right skipping len(after_title)
								# match title to remainder
									# log error if necessary
								# if any errors, don't bother setting title + others, just leave title as filename
							# else
								# split from left
								# match to variables in filename_format
						
						# if source json
							# create .info.json
							# attempt to open info.json
								# except:
									# set fallback_filename = True
								# else:
									# parse json if each exists & not empty string
									# replace above from filename where present
									# map ext to video_format
						# for thumb_ext = webp, avif, jpg, jpeg, png, gif
							# if filename + thumb_ext exists in folder, set thumbnail and break
						# create a namedtuple or something to add to the db (decide on individually or executescript)
					# list_videos by folder id
					# update db video_count by folder id
				# set task status 0, folder/of/file/of 0, message = Completed
				# if with_warnings = True, message = Completed with warnings
				# set_task w/ above
	
	threading.Thread(target = run_refresh_db(rescan)).start()

def add_folder(folder_name, folder_path, web_path, video_count):
	db = get_db()
	db.execute('INSERT INTO folders (folder_name, folder_path, web_path, video_count) VALUES (?, ?, ?, ?)', (
		folder_name,
		folder_path,
		web_path,
		video_count
		))
	db.commit()

def update_folder(id, video_count):
	db = get_db()
	db.execute('UPDATE folders SET video_count = ? WHERE id = ?', (video_count, id))
	db.commit()

def add_video(folder_id, filename, thumbnail, position, playlist_index, video_id, video_url, title, description, upload_date, modification_time, uploader, uploader_url, duration, view_count, like_count, dislike_count, average_rating, categories, tags, height, vcodec, video_format, fps):
	db = get_db()
	db.execute('INSERT INTO videos (folder_id, filename, thumbnail, position, playlist_index, video_id, video_url, title, description, upload_date, modification_time, uploader, uploader_url, duration, view_count, like_count, dislike_count, average_rating, categories, tags, height, vcodec, video_format, fps) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (
		folder_id,
		filename,
		thumbnail,
		position,
		playlist_index,
		video_id,
		video_url,
		title,
		description,
		upload_date,
		modification_time,
		uploader,
		uploader_url,
		duration,
		view_count,
		like_count,
		dislike_count,
		average_rating,
		categories,
		tags,
		height,
		vcodec,
		video_format,
		fps
		))
	db.commit()

def list_folders():
	return get_db().execute('SELECT * FROM folders').fetchall()

def list_videos(folder_id):
	# todo: limit # returned from params?
	# returns position + playlist_index so can choose how to sort (show choice if both not null)
	# todo: add sort_by = default (= playlist_index desc) arg to func
	# returns filename so refresh can remove existing from files to check
	try:
		folder_id = int(folder_id)
	except TypeError as e:
		raise TypeError('folder_id not an integer') from e
	
	return get_db().execute('SELECT id, title, thumbnail, duration, position, playlist_index, filename FROM videos WHERE folder_id = ?', (folder_id, )).fetchall()

def get_video(id):
	try:
		id = int(id)
	except TypeError as e:
		raise TypeError('id not an integer') from e
	
	return get_db().execute('SELECT videos.*, folders.web_path FROM videos INNER JOIN folders ON videos.folder_id = folders.id WHERE videos.id = ?', (id, )).fetchone()

@blueprint.route('/refresh')
@login_required('user', api = True)
def refresh():
	"""Scan only new files for videos"""
	try:
		refresh_db()
	except (BlockingIOError, sqlite3.OperationalError) as e: # also add thread error
		return 'failed' # jsonify with str(e) as message
	except # thread failure
		return 'failed' # jsonify etc
	
	return 'running'

@blueprint.route('/rescan')
@login_required('admin', api = True)
def rescan():
	"""Clear existing data and rescan all files for videos (restricted to admin users)"""
	try:
		refresh_db(rescan = True)
	# etc as above
	
	return 'running'

@blueprint.route('/status')
@login_required('user', api = True)
def status():
	"""Check the status of the currently-running task"""
	try:
		task = get_task()
	except sqlite3.OperationalError:
		return jsonify({'result': 'error',
						'message': 'Failed to get status'})
	
	# Convert sqlite3.Row object to dict for json
	task = {key: task[key] for key in task.keys()}
	
	return jsonify({'result': 'ok'
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
	except sqlite3.OperationalError:
		return jsonify({'result': 'error',
						'message': 'Failed to clear error'})
	
	return jsonify({'result': 'ok'})

@blueprint.route('/playlists')
@login_required('guest', api = True)
def playlists():
	try:
		folders = list_folders()
	except sqlite3.OperationalError:
		return jsonify({'result': 'error',
						'message': 'Failed to list playlists'})
	
	# Convert list of sqlite3.Row objects to list of dicts for json, removing disk paths
	folders = [{key: row[key] for key in row.keys() if key != 'folder_path'} for row in folders]
	
	return jsonify({'result': 'ok'
					'data': folders})

@blueprint.route('/playlist/<int:folder_id>')
@login_required('guest', api = True)
def playlist(folder_id):
	try:
		# todo: add sort
		videos = list_videos(folder_id)
	except sqlite3.OperationalError:
		return jsonify({'result': 'error',
						'message': 'Failed to list videos'})
	except TypeError as e:
		return jsonify({'result': 'error',
						'message': str(e)})
	
	# Convert list of sqlite3.Row objects to list of dicts for json, removing filenames
	videos = [{key: row[key] for key in row.keys() if key != 'status'} for row in videos]
	
	return jsonify({'result': 'ok'
					'data': videos})

@blueprint.route('/video/<int:video_id>')
@login_required('guest', api = True)
def video(video_id):
	try:
		video = get_video(id)
	except sqlite3.OperationalError:
		return jsonify({'result': 'error',
						'message': 'Failed to get video'})
	except TypeError as e:
		return jsonify({'result': 'error',
						'message': str(e)})
	
	# Convert sqlite3.Row object to dict for json
	video = {key: video[key] for key in video.keys()}
	
	# todo: format upload_date (YYYYMMDD), modification_time (timestamp), HTTP basic auth in web path
	
	return jsonify({'result': 'ok'
					'data': video})