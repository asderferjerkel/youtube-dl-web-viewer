from app import app

@app.route('/')
def index():
	return 'video page!'