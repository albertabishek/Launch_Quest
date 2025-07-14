from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from models import User, db
from datetime import datetime, timezone
import pytz  # Added for time zone handling

admin = Blueprint('admin', __name__)

@admin.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('main.home'))
    users = User.query.all()
    return render_template('admin.html', users=users)

@admin.route('/update_user_plan', methods=['POST'])
@login_required
def update_user_plan():
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    user_id = request.form.get('user_id')
    new_plan = request.form.get('plan') or 'free'
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    user.plan = new_plan
    if new_plan == 'free':
        user.credits = 5
        user.static_credits = 0
        user.dynamic_credits = 0
    elif new_plan == 'pro':
        user.credits = 50
        user.static_credits = 0
        user.dynamic_credits = 0
    elif new_plan == 'premium':
        user.credits = 0
        user.static_credits = 50
        user.dynamic_credits = 20
    elif new_plan == 'enterprise':
        user.credits = None
        user.static_credits = None
        user.dynamic_credits = None
    db.session.commit()
    return jsonify({'success': True})

@admin.route('/set_plan_expiration', methods=['POST'])
@login_required
def set_plan_expiration():
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
        
    user_id = request.form.get('user_id')
    expiration_str = request.form.get('expiration')
    user = User.query.get(user_id)
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
        
    if expiration_str:
        try:
            # The date comes from the form as a string 'YYYY-MM-DD'
            naive_datetime = datetime.strptime(expiration_str, '%Y-%m-%d')
            
            # Get the target user's timezone, fallback to UTC
            user_tz = pytz.timezone(user.timezone if user.timezone in pytz.all_timezones else 'UTC')
            
            # Localize the naive datetime to the user's timezone (end of day)
            local_dt = user_tz.localize(naive_datetime.replace(hour=23, minute=59, second=59))
            
            # Convert to UTC for storage
            utc_dt = local_dt.astimezone(pytz.utc)
            
            # Store as a naive datetime object in the database
            user.plan_expiration = utc_dt.replace(tzinfo=None)
        except ValueError:
            return jsonify({'error': 'Invalid date format'}), 400
    else:
        user.plan_expiration = None
        
    db.session.commit()
    return jsonify({'success': True})

@admin.route('/toggle_admin/<int:user_id>', methods=['POST'])
@login_required
def toggle_admin(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return jsonify({'error': 'Cannot modify your own admin status'}), 400
    user.is_admin = not user.is_admin
    db.session.commit()
    return jsonify({'success': True, 'is_admin': user.is_admin})

@admin.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return jsonify({'error': 'Cannot delete yourself'}), 400
    db.session.delete(user)
    db.session.commit()
    return jsonify({'success': True})