import json
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, current_user, login_required
from flask_wtf.csrf import CSRFProtect
from flask_socketio import SocketIO, join_room, leave_room, emit
from config import Config
from models import db, User
from extensions import mail, socketio, online_users
from flask_migrate import Migrate
from datetime import datetime, timezone, UTC
from markupsafe import Markup
import pytz  # Added for time zone handling

# --- NEW: Import OAuth from the new blueprint ---
from blueprints.oauth import oauth_bp, oauth

app = Flask(__name__)
app.config.from_object(Config)

csrf = CSRFProtect(app)
db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'auth.login'
mail.init_app(app)
migrate = Migrate(app, db)
socketio.init_app(app)

# --- NEW: Initialize OAuth with the app context ---
oauth.init_app(app)

oauth.register(
    name='google',
    client_id=app.config.get('GOOGLE_CLIENT_ID'),
    client_secret=app.config.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# --- NEW: Interceptor to handle incomplete accounts ---
@app.before_request
def check_for_incomplete_account():
    if current_user.is_authenticated and current_user.password_hash is None:
        # Allowed endpoints for users who haven't set a password
        allowed_endpoints = ['auth.complete_account', 'auth.logout', 'static']
        if request.endpoint not in allowed_endpoints:
            return redirect(url_for('auth.complete_account'))
        
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.template_filter('make_aware')
def make_aware(dt):
    """Convert a datetime to UTC offset-aware if it exists."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc)

@app.template_filter('localtime')
def localtime_filter(dt, user_timezone=None, format='%Y-%m-%d %H:%M %Z'):
    """Convert a UTC datetime or ISO string to the user's local time zone for display."""
    if dt is None:
        return ""

    # FIX: Check if the input is a string and convert it to a datetime object first.
    if isinstance(dt, str):
        try:
            # Handle ISO format strings from JSON/SocketIO events
            if dt.endswith('Z'):
                dt = dt.replace('Z', '+00:00')
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return dt # Return original string if it's not a valid date format

    # Default to current user's timezone if not provided
    if user_timezone is None and current_user.is_authenticated:
        user_timezone = current_user.timezone
        
    # Fallback to UTC if no timezone is available
    if not user_timezone or user_timezone not in pytz.all_timezones:
        user_timezone = 'UTC'
        
    try:
        user_tz = pytz.timezone(user_timezone)
    except pytz.UnknownTimeZoneError:
        user_tz = pytz.UTC
        
    # Make the datetime object aware of its timezone (either from parsing or by assuming UTC)
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    
    # Convert to user's local time
    dt_local = dt.astimezone(user_tz)
    return dt_local.strftime(format)


# Define the custom json_script filter
@app.template_filter('json_script')
def json_script_filter(value, id):
    json_data = app.jinja_env.filters['tojson'](value)
    return Markup(f'<script id="{id}" type="application/json">{json_data}</script>')

 
@app.template_filter('to_localtime')
def to_localtime(dt, user_tz):
    if dt is None:
        return None
    try:
        local_tz = timezone(user_tz)
    except:
        local_tz = UTC
    utc_dt = dt.replace(tzinfo=UTC)
    local_dt = utc_dt.astimezone(local_tz)
    return local_dt

@app.template_filter('utc_isoformat')
def utc_isoformat(dt):
    if dt is None:
        return ''
    return dt.replace(tzinfo=UTC).isoformat()

@app.template_filter('formatdatetime')
def formatdatetime(value, format='%Y-%m-%d %H:%M'):
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            # Handle ISO format with or without 'Z'
            if value.endswith('Z'):
                value = value.replace('Z', '+00:00')
            value = datetime.fromisoformat(value)
        except ValueError:
            return value # Return original string if parsing fails
    if isinstance(value, datetime):
        return value.strftime(format)
    return value

@app.template_filter('ordinal')
def ordinal_filter(n):
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return str(n) + suffix

@app.template_filter('from_json')
def from_json_filter(value):
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None
    
@socketio.on('disconnect')
def on_disconnect():
    """Handles user disconnection to update online presence."""
    sid = request.sid
    room_to_update = None
    for room, users in list(online_users.items()):
        if sid in users:
            del online_users[room][sid]
            room_to_update = room
            break
    if room_to_update:
        room_users = list(online_users[room_to_update].values())
        emit('update_online_users', {'users': room_users}, room=room_to_update)
 
from blueprints.auth import auth
from blueprints.quiz_management import quiz_management
from blueprints.quiz_taking import quiz_taking
from blueprints.events import q_events
from blueprints.main import main
from blueprints.admin import admin


app.register_blueprint(auth)
app.register_blueprint(quiz_management)
app.register_blueprint(quiz_taking)
app.register_blueprint(q_events)
app.register_blueprint(main)
app.register_blueprint(admin)
app.register_blueprint(oauth_bp)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    socketio.run(app, debug=True)