import functools

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from app.auth import login_required
from app.db import get_db

blueprint = Blueprint('index', __name__)

@blueprint.route('/')
@login_required('guest')
def index():
	# check if db needs updating: wrap with @request_queued (after login_required) + import from app.helpers
		 # see https://exploreflask.com/en/latest/views.html
	# do the same for check_conf (change to @warn_conf)
	# could do the same for @require_db, @require_first_run
	# no video/folder selected to start
	# feed w/ folder list
	# set some var if guest so JS doesn't call /api/status at all
	# many dangers: https://semgrep.dev/docs/cheat-sheets/flask-xss/ https://flask.palletsprojects.com/en/1.1.x/security/
	return render_template('index.html')