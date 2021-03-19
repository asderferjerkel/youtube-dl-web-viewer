DROP TABLE IF EXISTS folders;
DROP TABLE IF EXISTS videos;
DROP TABLE IF EXISTS params;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS tasks;
DROP TABLE IF EXISTS error_log;

CREATE TABLE folders (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	folder_name TEXT NOT NULL,
	folder_path TEXT NOT NULL,
	web_path TEXT NOT NULL,
	video_count INTEGER NOT NULL
);

CREATE TABLE videos (
	id INTEGER PRIMARY KEY,
	folder_id INTEGER NOT NULL,
	filename TEXT NOT NULL,
	thumbnail TEXT,
	position INTEGER,
	playlist_index INTEGER,
	video_id TEXT,
	title TEXT,
	description TEXT,
	upload_date TEXT,
	modification_time TEXT,
	uploader TEXT,
	uploader_url TEXT,
	duration INTEGER,
	view_count INTEGER,
	like_count INTEGER,
	dislike_count INTEGER,
	average_rating NUMERIC,
	categories TEXT,
	tags TEXT,
	height INTEGER,
	video_format TEXT,
	vcodec TEXT,
	fps NUMERIC,
	FOREIGN KEY (folder_id) REFERENCES folders (id)
);

CREATE TABLE params (
	last_refreshed INTEGER NOT NULL,
	refresh_interval INTEGER NOT NULL,
	disk_path TEXT NOT NULL,
	web_path TEXT NOT NULL,
	metadata_source TEXT NOT NULL,
	filename_format TEXT,
	filename_delimiter TEXT,
	guests_can_view INTEGER NOT NULL
);

INSERT INTO params (last_refreshed, refresh_interval, disk_path, web_path, metadata_source, filename_format, filename_delimiter, guests_can_view) VALUES (
	'0',
	'86400',
	'/home/user/videos/',
	'https://example.com/videos/',
	'json',
	'{position}{title}{id}{date}',
	' - ',
	'0'
);

CREATE TABLE users (
	id INTEGER PRIMARY KEY AUTOINCREMENT,
	username TEXT NOT NULL,
	password TEXT NOT NULL,
	is_admin INTEGER NOT NULL DEFAULT 0
);

/* status = 0 (not running), 1 (running), -1 (error) */
CREATE TABLE tasks (
	status INTEGER NOT NULL,
	folder INTEGER,
	of_folders INTEGER,
	file INTEGER,
	of_files INTEGER,
	message TEXT
	);

INSERT INTO tasks (status) VALUES (0);

CREATE TABLE error_log (
	timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
	level TEXT NOT NULL,
	message TEXT NOT NULL
);