from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import User, db
# UPDATED: Import CompleteAccountForm alongside the others
from forms import LoginForm, RegisterForm, CompleteAccountForm
from datetime import datetime, timezone
import re
import pytz

from utils import reset_credits
auth = Blueprint('auth', __name__)



@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        # IMPORTANT: Check if the password hash exists before checking the password
        if user and user.password_hash and check_password_hash(user.password_hash, form.password.data):
            login_user(user)
            # This now correctly calls the imported function
            reset_credits(user)
            flash('Login successful!', 'success')
            return redirect(url_for('main.home'))
        else:
            flash('Invalid email or password.', 'danger')
    return render_template('login.html', form=form)


@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    form = RegisterForm()
    if form.validate_on_submit():
        password = form.password.data
        confirm_password = request.form.get('confirm_password')
        timezone_str = form.timezone.data
        
        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'danger')
            return render_template('register.html', form=form)
        if not re.search(r'[A-Za-z]', password) or not re.search(r'\d', password) or not re.search(r'[\W_]', password):
            flash('Password must contain letters, numbers, and symbols.', 'danger')
            return render_template('register.html', form=form)
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html', form=form)
        if timezone_str not in pytz.all_timezones:
            flash('Invalid time zone selected.', 'danger')
            return render_template('register.html', form=form)

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(
            username=form.username.data,
            email=form.email.data,
            password_hash=hashed_password,
            timezone=timezone_str
        )
        db.session.add(new_user)
        db.session.commit()
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('register.html', form=form)

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('main.home'))

# --- Route for completing OAuth user account setup ---
@auth.route('/complete-account', methods=['GET', 'POST'])
@login_required
def complete_account():
    # If the user already has a password, they don't need to be here.
    if current_user.password_hash:
        return redirect(url_for('main.home'))

    form = CompleteAccountForm()
    if form.validate_on_submit():
        # Set the password and update the timezone from the form
        current_user.password_hash = generate_password_hash(form.password.data, method='pbkdf2:sha256')
        current_user.timezone = form.timezone.data
        db.session.commit()
        
        flash('Your account is now fully set up! You can now log in with your email and password.', 'success')
        return redirect(url_for('main.home'))

    return render_template('complete_account.html', form=form)