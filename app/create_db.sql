DROP TABLE IF EXISTS folders;
DROP TABLE IF EXISTS videos;
DROP TABLE IF EXISTS thumbs;
DROP TABLE IF EXISTS params;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS tasks;
DROP TABLE IF EXISTS error_log;

CREATE TABLE folders (
	id INTEGER PRIMARY KEY,
	folder_name TEXT NOT NULL,
	folder_path TEXT NOT NULL,
	video_count INTEGER
);

CREATE TABLE videos (
	id INTEGER PRIMARY KEY,
	folder_id INTEGER NOT NULL,
	filename TEXT NOT NULL,
	thumbnail TEXT,
	thumbnail_format TEXT,
	position INTEGER,
	playlist_index INTEGER,
	video_id TEXT,
	video_url TEXT,
	title TEXT,
	sort_title TEXT,
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
	vcodec TEXT,
	video_format TEXT,
	fps NUMERIC,
	FOREIGN KEY (folder_id) REFERENCES folders (id)
);

CREATE TABLE thumbs (
	id INTEGER PRIMARY KEY,
	video_id INTEGER NOT NULL,
	thumb_format TEXT,
	thumb_data TEXT,
	format_priority INTEGER,
	FOREIGN KEY (video_id) REFERENCES videos (id)
);

CREATE TABLE params (
	setup_complete INTEGER NOT NULL,
	last_refreshed NUMERIC NOT NULL,
	refresh_interval INTEGER NOT NULL,
	disk_path TEXT NOT NULL,
	web_path TEXT NOT NULL,
	metadata_source INTEGER NOT NULL,
	filename_format TEXT,
	filename_delimiter TEXT,
	generate_thumbs INTEGER NOT NULL,
	replace_underscores INTEGER NOT NULL,
	guests_can_view INTEGER NOT NULL
);

INSERT INTO params (
	setup_complete,
	last_refreshed,
	refresh_interval,
	disk_path,
	web_path,
	metadata_source,
	filename_format,
	filename_delimiter,
	generate_thumbs,
	replace_underscores,
	guests_can_view
) VALUES (
	'0',
	'0',
	'86400',
	'/home/user/videos/',
	'https://example.com/videos/',
	'1',
	'{position}{title}{id}{date}',
	' - ',
	'1',
	'1',
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