#!/usr/bin/python3

import logging
import sys
logging.basicConfig(stream=sys.stderr)

# Set the path to somewhere accessible to your webserver. You will symlink this to your app folder.
# You don't need to change ytdl-web to change the URL you access it from: that's done in your webserver config.
sys.path.insert(0, '/var/www/asdfghjkl.me.uk/video')
from app import app as application

# Set a random secret to protect the session ID
application.secret_key = 'Dada34243SddSMAUSadsmajdsidasdas'