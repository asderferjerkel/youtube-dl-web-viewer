#!/usr/bin/env python3

import logging
import sys
logging.basicConfig(stream=sys.stderr)

# Set the path based on where you've extracted youtube-dl-web-viewer/
sys.path.insert(0, '/home/asdfghjkl/youtube-dl-web-viewer')
from app import app as application