from waitress import serve
from main import app

# threads=16: a few slow POS queries can no longer starve static/login requests.
# channel_timeout below ARR's 120s so waitress drops dead connections first.
serve(app, host="127.0.0.1", port=5000, threads=16, channel_timeout=90)