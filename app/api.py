import functools
import json
import threading
try:
	from pysqlite3 import dbapi2 as sqlite3
except ImportError:
	import sqlite3

from collections import OrderedDict
from itertools import islice
from datetime import datetime, timezone

from pathlib import Path
import urllib
import re
from io import BytesIO
import base64

from flask import Blueprint, g, current_app, request, session, jsonify, escape
from flask_wtf import csrf
from wtforms.validators import ValidationError

try:
	from PIL import Image, features
except ImportError:
	Image = None
	features = None

from app.db import get_db, get_params, column_exists
from app.auth import login_required
from app.helpers import format_duration, escape_fts_query

blueprint = Blueprint('api', __name__, url_prefix='/api')

# todo: deal with cancelling tasks on server stop

def init_app(app):
	"""Reset running task on server restart"""
	with app.app_context():
		try:
			set_task()
		except sqlite3.OperationalError as e:
			# Task table could be missing if db not initialised
			current_app.logger.warning(f'Could not reset tasks: {e}')

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
	query = 'SELECT * FROM tasks ORDER BY rowid LIMIT 1'
	return get_db().execute(query).fetchone()

def set_task(status = 0, folder = None, of_folders = None, file = None, of_files = None, message = None):
	"""
	Set the currently running task.
	Specify status = 0 (not running, default), 1 (running), -1 (error); everything else is blanked unless supplied
	"""
	db = get_db()
	query = ('UPDATE tasks SET '
			 'status = ?, folder = ?, of_folders = ?, file = ?, '
			 'of_files = ?, message = ? ')
	db.execute(query, (status, folder, of_folders, file, of_files, message))
	db.commit()

# Compile non-alphanumeric regex for sortable title
non_alpha_re = re.compile('[\W_]+', re.UNICODE)
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
			
			# Lock running task
			try:
				set_task(status = 1, message = 'Initialising refresh')
			except sqlite3.OperationalError as e:
				# Fail if can't set lock
				raise sqlite3.OperationalError('Refresh: Could not lock task') from e
			
			if rescan:
				app.logger.debug('Full rescan, clearing tables')
				# Clear existing videos and folders
				try:
					db.execute('DELETE FROM videos')
					db.execute('DELETE FROM folders')
				except sqlite3.OperationalError as e:
					raise sqlite3.OperationalError('Refresh: Could not clear existing data') from e
				else:
					db.commit()
			
			with_warnings = False
			new_folders = 0
			new_videos = 0
			
			# Prepare thumbnail conversion
			generate_thumbs = False
			if (params['generate_thumbs'] and features is not None):
				# Enabled and Pillow installed
				te = app.config.get('THUMBNAIL_EXTENSIONS')
				ts = app.config.get('THUMBNAIL_SIZE')
				tq = app.config.get('THUMBNAIL_QUALITY')
				tf = app.config.get('THUMBNAIL_FORMATS')
				# Check app config
				if (isinstance(te, dict) and
					isinstance(ts, tuple) and len(ts) == 2 and
					isinstance(ts[0], int) and isinstance(ts[1], int) and
					isinstance(tq, int) and 1 <= tq <= 95 and
					isinstance(tf, dict)):
					# THUMBNAIL_EXTENSIONS is a dict
					# THUMBNAIL_SIZE is a pair of integers
					# THUMBNAIL_QUALITY is integer 1-95
					# THUMBNAIL_FORMATS is a dict of formats
					# Check for Pillow support for desired image formats
					pillow_features = features.get_supported_codecs() + features.get_supported_modules()
					# Supported if in pillow features and has matching MIME
					# type in THUMBNAIL_EXTENSIONS
					supported_formats = {key: value for key, value in tf.items() if (key in pillow_features and '.' + str(key) in te)}
					
					if len(supported_formats) > 0:
						# At least one format supported
						generate_thumbs = True
						# All formats (inc unsupported) default to no data
						thumbs_to_generate = []
						app.logger.debug('Generating thumbnails: ' + str(', '.join(supported_formats.keys())))
					else:
						with_warnings = True
						app.logger.warning('Thumbnail generation enabled but no supported image formats found')
				else:
					with_warnings = True
					app.logger.warning('Thumbnail generation disabled: config.py THUMBNAIL_SIZE must be integer maxwidth, maxheight; THUMBNAIL_QUALITY must be integer 1-95; THUMBNAIL_EXTENSIONS and THUMBNAIL_QUALITY must be dicts')
			
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
				
				# Convert folder list to {path: id}
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
			
			# List folders and subfolders on disk, including root
			disk_folders = [subfolder for subfolder in basepath.glob('**/')]
			folder_count = len(disk_folders)
			app.logger.debug('Found folders: ' + str(disk_folders))
			
			# Scan each folder for video files
			for folder_index, folder in enumerate(disk_folders):
				app.logger.debug('Scanning folder #' + str(folder_index + 1) + ' of ' + str(folder_count) + ': "' + str(folder) + '"')
				try:
					set_task(status = 1, folder = folder_index + 1, of_folders = folder_count, message = 'Scanning folder')
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
					if params['metadata_source']:
						# Multiple file extensions (.info.json) require suffixes, but they are greedy and eat names with dots so we check the string end instead
						if file.name.endswith(app.config['METADATA_EXTENSION']):
							metadatas.append(file)
				
				if len(files) > 0:
					# Found video files
					app.logger.debug('Found ' + str(len(files)) + ' files')
					# Check if the folder exists in the database, if the database has folders
					# DB stores folder paths relative to basepath so use that to compare
					folder_relative = folder.relative_to(basepath)
					if not rescan and (db_folders and str(folder_relative) in db_folders):
						folder_id = db_folders[str(folder_relative)]
						app.logger.debug('Found existing folder at ID ' + str(folder_id))
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
						
						# All videos are unseen
						new_video_count = len(files)
						
						try:
							# Store path relative to basepath
							folder_id = add_folder(folder_name, str(folder_relative), len(files))
						except sqlite3.OperationalError:
							with_warnings = True
							app.logger.warning('Refresh: Could not add new folder "' + str(folder_relative) + '" to database, skipping')
							# Skip to next folder
							continue
						else:
							new_folders += 1
					
					# Iterate through the subfolder's files
					for file_index, file in enumerate(files):
						if file_index % 10 == 0:
							# Update task every 10 files
							try:
								set_task(status = 1, folder = folder_index + 1, of_folders = folder_count, file = file_index + 1, of_files = new_video_count, message = 'Scanning for new videos')
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
								app.logger.debug('Video #' + str(file_index + 1) + ' matched thumbnail ' + str(thumb.name))
								# Store filename without path
								video['thumbnail'] = thumb.name
								if generate_thumbs:
									# Store relative path for conversion
									video['thumb_path'] = folder.joinpath(thumb)
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
								app.logger.debug('Video #' + str(file_index + 1) + ' matched metadata ' + str(meta.name))
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
								try:
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
						video['sort_title'] = non_alpha_re.sub('', video['title'])
						
						# Add to database
						app.logger.debug('Adding video #' + str(file_index + 1) + ': "' + str(video['title']) + '"')
						try:
							video_id = add_video(video)
						except sqlite3.OperationalError as e:
							with_warnings = True
							app.logger.warning('Refresh: Could not add video "' + video['filename'] + '" to the database: ' + str(e))
						else:
							new_videos += 1
							if (generate_thumbs and video['thumbnail'] is not None):
								# Queue thumbnail for conversion
								thumbs_to_generate.append(
											{'id': video_id,
											 'path': video['thumb_path'],
											 'data': {}})
			
			# Generate small thumbnails
			if generate_thumbs:
				total_thumbs = len(thumbs_to_generate)
				if total_thumbs > 0:
					for thumb_index, thumb in enumerate(thumbs_to_generate):
						if thumb_index % 5 == 0:
							# Update task every 5 thumbnails
							try:
								set_task(status = 1, folder = 0, of_folders = 0, file = thumb_index + 1, of_files = total_thumbs, message = 'Generating thumbnails')
							except sqlite3.OperationalError:
								with_warnings = True
								app.logger.warning('Refresh: Could not update task status')
						
						try:
							# Read thumbnail file
							with Image.open(basepath.joinpath(thumb['path'])) as img:
								if img.mode != 'RGB':
									# Just in case
									img = img.convert('RGB')
								# Shrink if over max, maintaining aspect ratio
								img.thumbnail(app.config['THUMBNAIL_SIZE'])
								# Export each supported format
								for fmt in supported_formats:
									# New empty stream
									stream = BytesIO()
									try:
										# method is only used by webp: 0 (fast) - 6 (slow)
										img.save(stream, format = supported_formats[fmt]['export_format'], quality = app.config['THUMBNAIL_QUALITY'], method = 2)
									except OSError as e:
										with_warnings = True
										app.logger.warning('Could not save thumbnail: ' + str(e))
									else:
										# Encode format as base64 data: URL
										ext = '.' + str(fmt)
										mime = app.config['THUMBNAIL_EXTENSIONS'][ext]
										thumb['data'][fmt] = (
											'data:' + mime + ';base64,' + 
											base64.encodebytes(
												stream.getvalue()
											).decode('ascii')
										)
										app.logger.debug('Created ' + str(fmt) + ' thumbnail for video ID ' + str(thumb['id']))
						except OSError as e:
							with_warnings = True
							app.logger.warning('Could not open thumbnail: ' + str(e))
						
					# Add thumbs to database
					try:
						set_task(status = 1, message = 'Adding thumbnails to database')
					except sqlite3.OperationalError:
						with_warnings = True
						app.logger.warning('Refresh: Could not update task status')
					
					for thumb in thumbs_to_generate:
						for fmt, data in thumb['data'].items():
							try:
								add_thumbnail(thumb['id'], fmt, data)
							except sqlite3.OperationalError:
								with_warnings = True
								app.logger.warning('Could not add ' + fmt + ' thumbnail for video ID ' + str(thumb['id']) + ' to database')
				
				else:
					app.logger.info('No thumbnails to generate')
			
			# Update last_refreshed (milliseconds since epoch in UTC)
			try:
				db.execute('UPDATE params SET last_refreshed = ?', (datetime.now().replace(tzinfo=timezone.utc).timestamp(), ))
			except sqlite3.OperationalError:
				app.logger.error('Refresh: Could not set last updated time')
			finally:
				# Task complete
				message = 'Scan completed with warnings' if with_warnings else 'Scan complete'
				stats = str(new_folders) + ' new folders, ' + str(new_videos) + ' new videos'
				app.logger.info(message + ' ' + stats)
				try:
					set_task(status = 0, message = message + "\n" + stats)
				except sqlite3.OperationalError:
					app.logger.error('Refresh: Could not set task to completed')
		
	threading.Thread(target = run_refresh_db(rescan)).start()

def add_folder(folder_name, folder_path, video_count):
	"""
	Add a new folder to the database.
	folder_path is relative to params['disk_path']
	Returns the folder's unique ID
	"""
	db = get_db()
	query = ('INSERT INTO folders (folder_name, folder_path, video_count) '
			 'VALUES (?, ?, ?)')
	db.execute(query, (folder_name, folder_path, video_count))
	id = db.execute('SELECT last_insert_rowid() FROM folders').fetchone()[0]
	db.commit()
	return id

def update_folder(id, video_count):
	"""Update the number of videos in a folder by its ID"""
	db = get_db()
	query = 'UPDATE folders SET video_count = ? WHERE id = ?'
	db.execute(query, (video_count, id))
	db.commit()

def add_video(video):
	"""
	Add a video to the database.
	Supply a dict of parameters, all but folder_id and filename can be None
	Returns the video's unique ID
	"""
	db = get_db()
	query = ('INSERT INTO videos ('
			 'folder_id, filename, thumbnail, thumbnail_format, position, '
			 'playlist_index, video_id, video_url, title, sort_title, '
			 'description, upload_date, modification_time, uploader, '
			 'uploader_url, duration, view_count, like_count, dislike_count, '
			 'average_rating, categories, tags, height, vcodec, video_format, '
			 'fps) VALUES ('
				 '?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '
				 '?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?'
			 ')')
	
	db.execute(query, (video['folder_id'], video['filename'],
					   video['thumbnail'], video['thumbnail_format'],
					   video['position'], video['playlist_index'],
					   video['id'], video['webpage_url'], video['title'],
					   video['sort_title'], video['description'],
					   video['upload_date'], video['modification_time'],
					   video['uploader'], video['uploader_url'],
					   video['duration'], video['view_count'],
					   video['like_count'], video['dislike_count'],
					   video['average_rating'], video['categories'],
					   video['tags'], video['height'], video['vcodec'],
					   video['video_format'], video['fps']))
					   
	id = db.execute('SELECT last_insert_rowid() FROM folders').fetchone()[0]
	db.commit()
	return id

def add_thumbnail(video_id, thumb_format, thumb_data):
	"""
	Add a video's thumbnail to the database by its ID.
	One video can have many thumbnail formats. Each thumb_format has an integer
	priority from app.config['THUMBNAIL_FORMATS'][thumb_format]['priority'].
	thumb_format = Pillow codec/module name (e.g. 'jpg', 'webp')
	thumb_data = base64-encoded data: URL
	"""
	try:
		format_priority = current_app.config['THUMBNAIL_FORMATS'][
						  thumb_format]['priority']
	except KeyError as e:
		raise KeyError('No priority configured for format ' + 
					   str(thumb_format)) from e
	
	db = get_db()
	query = ('INSERT INTO thumbs ('
			 'video_id, thumb_format, thumb_data, format_priority) '
			 'VALUES (?, ?, ?, ?)')
	db.execute(query, (video_id, thumb_format, thumb_data, format_priority))
	db.commit()

def list_folders():
	"""
	Returns a list of folders with their ID, name, path and video count
	Sorts by folder path for tree then name order
	"""
	query = 'SELECT * FROM folders ORDER BY folder_path ASC'
	return get_db().execute(query).fetchall()

def list_videos(folder_id, sort_by = 'playlist_index',
				sort_direction = 'desc'):
	"""
	Returns a sorted list of videos with their ID, title, duration and filename
	"""
	try:
		folder_id = int(folder_id)
	except ValueError as e:
		raise ValueError('folder_id not an integer') from e
	
	# Check the column exists and is allowed for sorting
	if ((not column_exists('videos', sort_by)) or
		sort_by not in current_app.config['SORT_COLUMNS'].keys()):
		raise ValueError('Column unknown or not enabled for sort')
	
	if sort_direction in ['asc', 'desc']:
		direction_string = sort_direction.upper()
	else:
		raise ValueError('Sort direction must be "asc" or "desc"')
	
	sort_string = f"{sort_by} {direction_string} "
	if sort_by not in ['playlist_index', 'position', 'title']:
		# Secondary sorts for all but the above in case of dupe/missing values
		sort_string += (f", playlist_index {direction_string} "
						f", position {direction_string } ")
	# All sorts finally fall back to ID 
	sort_string += f", id {direction_string}"
	
	query = ('SELECT id, title, duration, filename '
			 'FROM videos WHERE folder_id = ? '
			f"ORDER BY {sort_string}")
	return get_db().execute(query, (folder_id, )).fetchall()

def get_video(id):
	"""Return a single video"""
	try:
		id = int(id)
	except ValueError as e:
		raise ValueError('ID is not an integer') from e
	
	query = ('SELECT folder_id, videos.id, filename, '
			 'thumbnail, thumbnail_format, video_id, '
			 'video_url, title, description, '
			 'strftime("%d/%m/%Y", upload_date) AS upload_date, '
			 'strftime("%d/%m/%Y %H:%M", modification_time) '
			 'AS modification_time, '
			 'uploader, uploader_url, duration, '
			 'view_count, like_count, dislike_count, '
			 'average_rating, categories, tags, '
			 'height, vcodec, video_format, '
			 'fps, folder_path, folder_name '
			 'FROM videos INNER JOIN folders ON folder_id = folders.id '
			 'WHERE videos.id = ?')
	return get_db().execute(query, (id, )).fetchone()

def get_thumbs(image_format, ids):
	"""
	Return small thumbnails as bytes in the requested image format
	for a list of video IDs
	Returns a row for each thumbnail with its video ID, image format and data
	"""
	# Sane maximum query size
	max_ids = 100
	
	if len(ids) > max_ids:
		raise ValueError('Too many IDs: max ' + str(max_ids) +
						' per query, ' + str(len(ids)) + ' were provided')
	if image_format not in current_app.config['THUMBNAIL_FORMATS'].keys():
		current_app.logger.info('Thumbnail format "' + str(image_format) +
								'" not recognised, falling back to jpg')
		image_format = 'jpg'
	try:
		ids = [int(id) for id in ids]
	except ValueError as e:
		raise ValueError('IDs must be integers') from e
	
	# Get the best format available up to the requested max for each ID
	try:
		max_priority = int(current_app.config['THUMBNAIL_FORMATS'][image_format]['priority'])
	except ValueError as e:
		raise TypeError('THUMBNAIL_FORMATS priority not an integer')
	
	query = ('SELECT video_id, thumb_format, thumb_data, '
			 'MAX(format_priority) as format_priority '
			 'FROM thumbs WHERE format_priority <= ? '
			f"AND video_id in ({', '.join(['?']*len(ids))}) "
			 'GROUP BY video_id')
	
	return get_db().execute(query, (max_priority, *ids)).fetchall()

def search_videos(field, search_query):
	"""
	List videos matching a fulltext query in the specified field
	Matches individual space-separated strings of minimum 3 characters
	(surround multiple strings with double quotes to match a phrase)
	"""
	# Sane maximum search query length
	max_query_length = 255
	
	try:
		max_results = int(current_app.config['MAX_SEARCH_RESULTS'])
	except ValueError as e:
		raise TypeError('MAX_SEARCH_RESULTS not an integer')
	
	if (
		field != 'all' and (
			# Check the column exists and is allowed for searching
			(not column_exists('videos_fts', field)) or
			field not in current_app.config['SEARCH_COLUMNS'].keys()
		)
	):
		raise ValueError('Search field unknown or not enabled for search')
	
	if len(search_query) > 255:
		raise ValueError('Query too long: max ' + str(max_query_length) +
						' characters, ' + str(len(search_query)) +
						' were provided')
	
	# Split into phrases and quote so punctuation doesn't cause syntax errors
	search_query = escape_fts_query(search_query)
	
	col_weights = ''
	if field == 'all':
		# Search entire table
		field = 'videos_fts'
		# Apply custom column weighting
		if isinstance(
			current_app.config.get('SEARCH_COLUMN_WEIGHTING'), tuple):
			col_weights = ("AND rank MATCH 'bm25"
						  f"{current_app.config['SEARCH_COLUMN_WEIGHTING']}"
						   "' ")
		else:
			current_app.logger.warning('SEARCH_COLUMN_WEIGHTING not tuple, '
									   'custom column weights disabled')
	
	query = ('SELECT videos.id, title, folder_name, snippet '
			 'FROM videos '
			 '	INNER JOIN '
			 '		(SELECT rowid, rank, '
					 # Using an unlikely-to-appear-otherwise marker 
					 # to convert to HTML later
			 '		 snippet(videos_fts, -1, "[*b*]", "[/*b*]", '
			 '				 "...", 64) AS snippet '
			 '		 FROM videos_fts '
			f"		 WHERE {field} MATCH ? {col_weights})"
			 '			ON videos.id = rowid '
				# Get video's folder name
			 '	INNER JOIN folders '
			 '		ON folder_id = folders.id '
			 'ORDER BY rank LIMIT ?')
	return get_db().execute(query, (search_query, max_results)).fetchall()


@blueprint.route('/refresh')
@login_required('user', api = True)
@csrf_protect # as potentially DOSable
def refresh():
	"""Scan only new files for videos"""
	try:
		refresh_db()
	except (BlockingIOError, sqlite3.OperationalError) as e: # todo: also add thread error
		current_app.logger.error('Failed to start refresh: ' + str(e))
		return jsonify({'result': 'error',
						'message': str(e)}), 500 # Inherited from parent
	
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
						'message': str(e)}), 500 # Inherited from parent

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
						'message': 'Failed to get status: ' +
						'Database error'}), 500
	
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
	"""Clear the latest task status"""
	try:
		set_task()
	except sqlite3.OperationalError as e:
		current_app.logger.error('Failed to clear status: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Failed to clear status: ' +
						'Database error'}), 500
	
	return jsonify({'result': 'ok'})

@blueprint.route('/prefs/<string:pref>/<string:value>')
@login_required('user', api = True)
@csrf_protect # as changes settings
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
								'message': 'Preferences missing from ' +
								'session, log out and in again'}), 400
		else:
			return jsonify({'status': 'error',
							'message': 'Unknown value for preference'}), 400
	else:
		return jsonify({'status': 'error',
						'message': 'Unknown preference'}), 400
	
	session['display_prefs'][pref] = value
	return jsonify({'result': 'ok',
					'message': 'Display preferences updated',
					'display_prefs': session['display_prefs']})

@blueprint.route('/playlists')
@login_required('guest', api = True)
def playlists():
	"""
	List playlists with their ID, name and video count, sorted alphabetically
	"""
	try:
		folders = list_folders()
	except sqlite3.OperationalError as e:
		current_app.logger.error('Failed to list playlists: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Failed to list playlists: ' +
						'Database error'}), 500
	
	if len(folders) == 0:
		return jsonify({'result': 'error',
						'message': 'No playlists'}), 404
	
	# List of dicts ordered alphabetically
	folders = [{key: row[key] for key in row.keys() if key != 'folder_path'}
			   for row in folders]
	
	return jsonify({'result': 'ok',
					'data': folders})

@blueprint.route('/playlist/<int:folder_id>', defaults = {
				 'sort_by': 'playlist_index', 'sort_direction': 'desc'})
@blueprint.route('/playlist/<int:folder_id>/<string:sort_by>/<string:sort_direction>')
@login_required('guest', api = True)
def playlist(folder_id, sort_by, sort_direction):
	"""
	List videos in a playlist by its ID
	Returns a dict of dicts indexed by the specified sort column and direction
	"""
	try:
		params = get_params()
	except sqlite3.OperationalError as e:
		current_app.logger.error('Failed to get params: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Failed to get params: ' +
						'Database error'}), 500
	
	try:
		videos = list_videos(folder_id, sort_by, sort_direction)
	except ValueError as e:
		return jsonify({'result': 'error',
						'message': 'Failed to get playlist: ' +
						str(e)}), 400 # Inherited from parent
	except TypeError as e:
		return jsonify({'result': 'error',
						'message': 'Playlist does not exist'}), 404
	except sqlite3.OperationalError as e:
		current_app.logger.error('Failed to get playlist: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Failed to list videos: ' +
						'Database error'}), 500
	
	if len(videos) == 0:
		return jsonify({'result': 'error',
						'message': 'Playlist does not exist'}), 404
	
	# List of dicts by sort order
	# Rename to reduce response size & format duration
	videos = [{'id': video['id'],
			   't': video['title'],
			   'd': format_duration(video['duration'])
			  } for video in videos]
	
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
						'message': 'Failed to get params: ' +
						'Database error'}), 500
	
	try:
		video = get_video(video_id)
	except ValueError as e:
		return jsonify({'result': 'error',
						'message': 'Failed to get video: ' +
						str(e)}), 400 # Inherited from parent
	except TypeError as e:
		return jsonify({'result': 'error',
						'message': 'Video does not exist'}), 404
	except sqlite3.OperationalError as e:
		current_app.logger.error('Failed to get video: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Failed to get video: ' +
						'Database error'}), 500
	
	if video is None:
		current_app.logger.info('No video returned')
		return jsonify({'result': 'error',
						'message': 'Video does not exist'}), 404
	
	# sqlite3.Row to dict for json
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
	
	return jsonify({'result': 'ok',
					'data': video})

@blueprint.route('/thumbs', methods = ['POST'], defaults = {
				 'image_format': 'jpg'})
@blueprint.route('/thumbs/<string:image_format>', methods = ['POST'])
@login_required('guest', api = True)
def thumbs(image_format):
	"""
	Get small thumbnails for a JSON array of video IDs in the requested format,
	falling back to compatible formats if the requested is unavailable
	Returns a dict of dicts indexed by video ID: {1: {'f': 'jpg', 'd': data}}
	"""
	video_ids = request.get_json(silent = True)
	if (video_ids is None or not isinstance(video_ids, list)):
		return jsonify({'result': 'error',
						'message': 'Invalid JSON request'}), 400
	
	try:
		thumbnails = get_thumbs(image_format, video_ids)
	except ValueError as e:
		return jsonify({'result': 'error',
						'message': 'Failed to get thumbnails: ' +
						str(e)}), 400 # Inherited from parent
	except TypeError as e:
		current_app.logger.error('Failed to get thumbnails: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Failed to get thumbnails: ' +
						'Configuration error'}), 500
	except sqlite3.OperationalError as e:
		current_app.logger.error('Failed to get thumbnails: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Failed to get thumbnails: ' +
						'Database error'}), 500
	
	# Dict of dicts indexed by video ID
	thumbnails = {thumb['video_id']: {'f': thumb['thumb_format'],
									  'd': thumb['thumb_data']}
									 for thumb in thumbnails}
	
	return jsonify({'result': 'ok',
					'data': thumbnails})

@blueprint.route('/search', methods = ['POST'], defaults = {
				 'field': 'title'})
@blueprint.route('/search/<string:field>', methods = ['POST'])
@login_required('guest', api = True)
def search(field):
	"""
	Fulltext search for videos by the specified metadata field (or 'all')
	Returns a ranked list of matches with video ID, title and matching snippet
	"""
	search_query = request.get_json(silent = True)
	if (not isinstance(search_query, str)):
		return jsonify({'result': 'error',
						'message': 'Invalid JSON request'}), 400
	if len(search_query) < 3:
		return jsonify({'result': 'error',
						'message': 'Search query must be 3+ characters'}), 400
	
	try:
		results = search_videos(field, search_query)
	except TypeError as e:
		current_app.logger.error('Failed to get search results: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Search failed: Configuration error'}), 500
	except ValueError as e:
		return jsonify({'result': 'error',
						'message': 'Search failed: ' +
						str(e)}), 400 # Inherited from parent
	except sqlite3.OperationalError as e:
		if e.args[0].startswith('fts5: syntax'):
			return jsonify({'result': 'error',
							'message': 'Search failed: syntax error'}), 400
		current_app.logger.error('Failed to get search results: ' + str(e))
		return jsonify({'result': 'error',
						'message': 'Search failed: Database error'}), 500
	
	# List of matches in rank order
	results = [{'id': result['id'],
				't': result['title'],
				'p': result['folder_name'],
				# Snippet has formatting so will be inserted as innerHTML,
				# so safely escape any existing HTML then convert our
				# custom markers to <strong></strong>
				's': str(escape(result['snippet']))
					 .replace('[*b*]', '<strong>')
					 .replace('[/*b*]', '</strong>')
			   } for result in results]
	
	# Format snippets
	for result in results:
		# Remove newlines if searching description or all
		if field in ['description', 'all']:
			result['s'] = result['s'].replace('\n', ' ')
		# Remove quotes and brackets if searching tags, categories or all
		if field in ['tags', 'categories', 'all']:
			# (double quotes already escaped to HTML entities)
			result['s'] = (result['s'].replace('&#34;', '')
									  .replace('[', '')
									  .replace(']', ''))
	
	return jsonify({'result': 'ok',
					'data': results})