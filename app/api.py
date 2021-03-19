import functools
import json

from pathlib import Path

from flask import Blueprint, g, request, session, jsonify

from app.db import get_db
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
	db.execute('UPDATE tasks SET status = ?, folder = ?, of_folders = ?, file = ?, of_files = ?, message = ?', (
		status,
		folder,
		of_folders,
		file,
		of_files,
		message
		))
	db.commit()

def refresh_db(rescan = False):
	db = get_db()
	
	try:
		if get_task()['status'] == 1:
			raise BlockingIOError('A task is already running')
	except sqlite3.OperationalError as e:
		raise sqlite3.OperationalError('Could not check for running tasks') from e
	
	if rescan:
		# Clear tables first
		try:
			db.execute('DELETE FROM videos')
			db.execute('DELETE FROM folders')
		except sqlite3.OperationalError as e:
			raise sqlite3.OperationalError('Could not clear existing data') from e
		else:
			db.commit()
	
	# thread it out
		# update status every 1 folder, 10 videos (unless error)
	
	# raise a diff exception for thread failure

def list_folders():
	return get_db().execute('SELECT id, folder_name, video_count FROM folders').fetchall()

def list_videos(folder_id):
	# todo: limit # returned from params?
	# returns position + playlist_index so can choose how to sort (show choice if both not null)
	# todo: add sort_by = default (= playlist_index desc) arg to func
	# returns filename so refresh can remove existing from files to check
	try:
		folder_id = int(folder_id)
	except TypeError as e:
		raise TypeError('folder_id not an integer') from e
	
	return get_db().execute('SELECT id, title, thumbnail, duration, position, playlist_index, filename FROM videos WHERE folder_id = ?', (folder_id)).fetchall()

def get_video(id):
	return

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
		return get_task() #jsonify
	except sqlite3.OperationalError:
		return 'failed' #jsonify

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
		return jsonify({'status': 'error'
						'message': 'Failed to clear error'})
	
	return jsonify({'status': 'ok'})

@blueprint.route('/playlists')
@login_required('guest', api = True)
def playlists():
	try:
		folders = list_folders()
	except sqlite3.OperationalError:
		return jsonify({'status': 'error'
						'message': 'Failed to list playlists'})
	
	# Convert list of sqlite3.Row objects to list of dicts for json
	folders = [{key: row[key] for key in row.keys()} for row in folders]
	
	return jsonify({'status': 'ok'
					'data': folders})

@blueprint.route('/playlist/<int:folder_id>')
@login_required('guest', api = True)
def playlist(folder_id):
	try:
		# todo: add sort
		videos = list_videos(folder_id)
	except sqlite3.OperationalError:
		return jsonify({'status': 'error'
						'message': 'Failed to list videos'})
	
	# Convert list of sqlite3.Row objects to list of dicts for json, removing filenames
	videos = [{key: row[key] for key in row.keys() if key != 'status'} for row in videos]
	
	return jsonify({'status': 'ok'
					'data': videos})

@blueprint.route('/video/<int:video_id>')
@login_required('guest', api = True)
def video(video_id):
	# todo: this whole thing
	return