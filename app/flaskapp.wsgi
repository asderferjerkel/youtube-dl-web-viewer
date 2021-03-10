import logging
import sys
logging.basicConfig(stream=sys.stderr)

# Set the path to the folder containing app/ (e.g. /path/to/youtube-dl-web-viewer)
sys.path.insert(0, '/home/asdfghjkl/youtube-dl-web-viewer')

from app import create_app
application = creat_app()