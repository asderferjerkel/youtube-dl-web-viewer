from flask import Flask
app = Flask(__name__)

# View functions must be imported in __init__.py as per https://flask.palletsprojects.com/en/1.1.x/patterns/packages/
from app import views