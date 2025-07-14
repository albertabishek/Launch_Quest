from flask import Blueprint, url_for, redirect, flash
from flask_login import login_user
from authlib.integrations.flask_client import OAuth
from models import db, User
import secrets

oauth_bp = Blueprint('oauth', __name__)

# This 'oauth' object will be initialized in app.py
oauth = OAuth()

def handle_google_login(user_info):
    """Handles the user logic after successful Google authentication."""
    
    google_id = user_info.get('sub')
    email = user_info.get('email')
    
    if not google_id or not email:
        flash('Google login failed. Could not retrieve required information.', 'danger')
        return redirect(url_for('auth.login'))

    # 1. Check if user exists via their Google ID
    user = User.query.filter_by(google_id=google_id).first()
    if user:
        login_user(user)
        return redirect(url_for('main.home'))

    # 2. If not, check if their email is already in use
    user = User.query.filter_by(email=email).first()
    if user:
        # Link the existing account to their Google ID
        user.google_id = google_id
        db.session.commit()
        login_user(user)
        flash('Your Google account has been linked to your existing account.', 'success')
        return redirect(url_for('main.home'))

    # 3. If no user exists, create a new one
    new_user = User(
        username=f"{user_info.get('given_name', 'user')}_{secrets.token_hex(4)}", # Create a unique username
        email=email,
        password_hash=None, # IMPORTANT: Password is None until they set it
        timezone='UTC',
        google_id=google_id
    )
    
    db.session.add(new_user)
    db.session.commit()
    login_user(new_user)
    
    # Redirect new users to complete their account setup
    flash('Welcome to RallyMind! Please complete your account setup.', 'info')
    return redirect(url_for('auth.complete_account'))

# --- Google Routes ---
@oauth_bp.route('/login/google')
def login_google():
    redirect_uri = url_for('oauth.authorize_google', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@oauth_bp.route('/login/google/callback')
def authorize_google():
    try:
        token = oauth.google.authorize_access_token()
        user_info = oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo').json()
        return handle_google_login(user_info)
    except Exception as e:
        flash(f'An error occurred during Google login: {e}', 'danger')
        return redirect(url_for('auth.login'))