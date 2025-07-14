from flask import Blueprint, render_template, redirect, url_for, flash, request, make_response, jsonify, current_app
from flask_login import login_required, current_user
from flask_socketio import emit, join_room
from models import Quiz, EventRegistration, User, db, ChatMessage, Attempt, Poll, PollOption, PollVote, Reaction
from extensions import mail, socketio, online_users  # Import from extensions
from flask_mail import Message
from datetime import datetime, timezone
import os
import io
import csv
from werkzeug.utils import secure_filename
import uuid
from tenacity import retry, stop_after_attempt, wait_fixed
import logging
from sqlalchemy import func, case
from sqlalchemy.orm import aliased
import json
import pytz  # Added for time zone handling

q_events = Blueprint('events', __name__)

# --- Setup for File Uploads ---
REGISTRATION_UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static', 'uploads')
if not os.path.exists(REGISTRATION_UPLOAD_FOLDER):
    os.makedirs(REGISTRATION_UPLOAD_FOLDER)

CHAT_UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static', 'uploads', 'chat')
if not os.path.exists(CHAT_UPLOAD_FOLDER):
    os.makedirs(CHAT_UPLOAD_FOLDER)

REGISTRATION_ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
CHAT_ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx', 'txt'}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def allowed_file(filename, allowed_set):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_set

def get_user_role(user, quiz):
    """Determines a user's role for a specific quiz."""
    if user.is_admin:
        return 'admin'
    if quiz.user_id == user.id:
        return 'creator'
    return 'participant'

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def send_email_with_retry(msg):
    mail.send(msg)

# --- ORIGINAL EVENT MANAGEMENT ROUTES ---

def get_events_data(query, page, per_page):
    """
    Refactored helper function to efficiently fetch quiz data and related user info.
    """
    now = datetime.now(timezone.utc)

    base_paginated = query.order_by(Quiz.start_time.desc()).paginate(page=page, per_page=per_page, error_out=False)
    quizzes = base_paginated.items
    quiz_ids = [q.id for q in quizzes]
    if not quiz_ids:
        return base_paginated, {}, {}, now

    verified_counts = dict(
        db.session.query(
            EventRegistration.quiz_id,
            func.count(EventRegistration.id)
        )
        .filter(
            EventRegistration.status == 'verified',
            EventRegistration.quiz_id.in_(quiz_ids)
        )
        .group_by(EventRegistration.quiz_id)
        .all()
    )

    for quiz in quizzes:
        quiz.registered_count = verified_counts.get(quiz.id, 0)

    user_regs = EventRegistration.query.filter(
        EventRegistration.quiz_id.in_(quiz_ids),
        EventRegistration.user_id == current_user.id
    ).all()
    user_registrations = {reg.quiz_id: reg for reg in user_regs}

    user_attempts_data = db.session.query(
        Attempt.quiz_id,
        func.count(Attempt.id)
    ).filter(
        Attempt.quiz_id.in_(quiz_ids),
        Attempt.user_id == current_user.id
    ).group_by(Attempt.quiz_id).all()
    user_attempts = {quiz_id: cnt for quiz_id, cnt in user_attempts_data}

    for quiz in quizzes:
        quiz.registration_closed = (
            (quiz.registration_end_time_utc and quiz.registration_end_time_utc < now) or
            quiz.registered_count >= quiz.max_users
        )

    base_paginated.items = quizzes
    return base_paginated, user_registrations, user_attempts, now

@q_events.route('/events')
@login_required
def events():
    page = request.args.get('page', 1, type=int)
    per_page = 9

    base_query = Quiz.query.filter_by(quiz_type='event')
    
    paginated_quizzes, user_registrations, user_attempts, now = get_events_data(base_query, page, per_page)
    
    return render_template(
        'events.html',
        quizzes=paginated_quizzes,
        user_registrations=user_registrations,
        user_attempts=user_attempts,
        now=now
    )

@q_events.route('/search_events')
@login_required
def search_events():
    search_term = request.args.get('search', '').lower()
    difficulty = request.args.get('difficulty', '')
    language = request.args.get('language', '')
    status = request.args.get('status', '')
    page = request.args.get('page', 1, type=int)
    per_page = 9

    query = Quiz.query.filter_by(quiz_type='event').join(User)

    if search_term:
        query = query.filter(
            (Quiz.title.ilike(f'%{search_term}%')) |
            (User.username.ilike(f'%{search_term}%')) |
            (Quiz.tags.ilike(f'%{search_term}%'))
        )
    if difficulty:
        query = query.filter(Quiz.difficulty == difficulty)
    if language:
        query = query.filter(Quiz.language == language)
    
    paginated_quizzes, user_registrations, user_attempts, now = get_events_data(query, page, per_page)

    if status:
        filtered_items = []
        for quiz in paginated_quizzes.items:
            is_open = not quiz.registration_closed
            is_started = quiz.start_time_utc and quiz.start_time_utc <= now
            if status == 'open' and is_open:
                filtered_items.append(quiz)
            elif status == 'closed' and quiz.registration_closed:
                filtered_items.append(quiz)
            elif status == 'started' and is_started:
                filtered_items.append(quiz)
        paginated_quizzes.items = filtered_items

    return render_template(
        '_quiz_grid.html',
        quizzes=paginated_quizzes,
        user_registrations=user_registrations,
        user_attempts=user_attempts,
        now=now
    )

@q_events.route('/event/<string:quiz_uuid>', methods=['GET', 'POST'])
@login_required
def event_details(quiz_uuid):
    quiz = Quiz.query.filter_by(uuid=quiz_uuid).first_or_404()
    now = datetime.now(timezone.utc)
    
    reg_count = EventRegistration.query.filter_by(quiz_id=quiz.id, status='verified').count()
    registration = EventRegistration.query.filter_by(quiz_id=quiz.id, user_id=current_user.id).first()
    
    registration_closed = (
        (quiz.registration_end_time_utc and quiz.registration_end_time_utc < now) or 
        reg_count >= quiz.max_users
    )

    if request.method == 'POST':
        current_reg_count = EventRegistration.query.filter_by(quiz_id=quiz.id, status='verified').count()
        current_registration_closed = (
            (quiz.registration_end_time_utc and quiz.registration_end_time_utc < now) or 
            current_reg_count >= quiz.max_users
        )
        
        if current_registration_closed:
            flash('Registration is now closed. You cannot register at this time.', 'danger')
            return redirect(url_for('events.event_details', quiz_uuid=quiz_uuid))
        
        if (not registration or registration.status == 'rejected') and not current_registration_closed:
            phone = request.form.get('phone')
            payment_screenshot = request.files.get('payment_screenshot')

            if not all([phone, payment_screenshot]):
                flash('Phone number and payment screenshot are required.', 'danger')
                return redirect(url_for('events.event_details', quiz_uuid=quiz_uuid))

            if not allowed_file(payment_screenshot.filename, REGISTRATION_ALLOWED_EXTENSIONS):
                flash('Invalid file type. Please upload an image (png, jpg, jpeg, gif).', 'danger')
                return redirect(url_for('events.event_details', quiz_uuid=quiz_uuid))

            filename = secure_filename(f"{uuid.uuid4()}_{payment_screenshot.filename}")
            payment_screenshot.save(os.path.join(REGISTRATION_UPLOAD_FOLDER, filename))

            if registration and registration.status == 'rejected':
                old_file = os.path.join(REGISTRATION_UPLOAD_FOLDER, registration.payment_screenshot)
                if os.path.exists(old_file):
                    try:
                        os.remove(old_file)
                    except Exception as e:
                        logger.error(f"Error removing old screenshot: {str(e)}")
                
                registration.phone = phone
                registration.payment_screenshot = filename
                registration.status = 'pending'
                registration.reason = None
            else:
                registration = EventRegistration(
                    quiz_id=quiz.id, user_id=current_user.id, name=current_user.username,
                    email=current_user.email, phone=phone, payment_screenshot=filename, status='pending'
                )
                db.session.add(registration)
            
            db.session.commit()

            try:
                msg = Message(
                    subject=f'Event Registration Confirmation - {quiz.title}', recipients=[current_user.email],
                    html=f"<p>Thank you for registering for {quiz.title}!</p><p>Your payment is pending verification.</p>"
                )
                send_email_with_retry(msg)
                flash('Registration successful! Awaiting payment verification.', 'success')
            except Exception as e:
                flash(f'Registration successful, but failed to send email: {str(e)}', 'warning')
            return redirect(url_for('quiz_management.my_quizzes'))

    return render_template(
        'event_details.html', quiz=quiz, registration=registration, current_user=current_user,
        now=now, reg_count=reg_count, registration_closed=registration_closed
    )

@q_events.route('/event/<int:quiz_id>/participants')
@login_required
def get_participant_count(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    reg_count = EventRegistration.query.filter_by(
        quiz_id=quiz.id, 
        status='verified'
    ).count()
    return jsonify({'count': reg_count})

# SocketIO events
@socketio.on('join_quiz')
def handle_join_quiz(data):
    quiz_id = data['quizId']
    socketio.server.enter_room(request.sid, f'quiz_{quiz_id}')

@socketio.on('update_registration')
def handle_update_registration(data):
    quiz_id = data['quizId']
    reg_count = EventRegistration.query.filter_by(
        quiz_id=quiz_id, 
        status='verified'
    ).count()
    
    # Broadcast to all clients in the quiz room
    socketio.emit('registration_update', {
        'quizId': quiz_id,
        'count': reg_count
    }, room=f'quiz_{quiz_id}')
    
    # Notify specific user about their status change
    if 'userId' in data and 'status' in data:
        socketio.emit('status_update', {
            'quizId': quiz_id,
            'userId': data['userId'],
            'status': data['status']
        }, room=request.sid)

@q_events.route('/event_dashboard/<string:quiz_uuid>')
@login_required
def event_dashboard(quiz_uuid):
    quiz = Quiz.query.filter_by(uuid=quiz_uuid).first_or_404()
    if quiz.user_id != current_user.id and not current_user.is_admin:
        flash('You do not have permission to view this dashboard.', 'danger')
        return redirect(url_for('quiz_management.my_quizzes'))
    
    page = request.args.get('page', 1, type=int)
    per_page = 10

    stats = db.session.query(
        func.count(EventRegistration.id).label('total'),
        func.count(case((EventRegistration.status == 'verified', 1))).label('verified'),
        func.count(case((EventRegistration.status == 'pending', 1))).label('pending'),
        func.count(case((EventRegistration.status == 'rejected', 1))).label('rejected')
    ).filter(EventRegistration.quiz_id == quiz.id).one()
    
    registrations = EventRegistration.query.filter_by(quiz_id=quiz.id)\
        .order_by(EventRegistration.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
        
    return render_template(
        'event_dashboard.html', 
        quiz=quiz, 
        registrations=registrations,
        reg_count=stats.total,
        verified_count=stats.verified,
        pending_count=stats.pending,
        rejected_count=stats.rejected
    )

@q_events.route('/export_registrations/<string:quiz_uuid>')
@login_required
def export_registrations(quiz_uuid):
    quiz = Quiz.query.filter_by(uuid=quiz_uuid).first_or_404()
    if quiz.user_id != current_user.id and not current_user.is_admin:
        flash('You do not have permission to export registrations.', 'danger')
        return redirect(url_for('quiz_management.my_quizzes'))
    registrations = EventRegistration.query.filter_by(quiz_id=quiz.id).all()
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Name', 'Email', 'Phone', 'Status', 'Timestamp (Local)', 'Reason'])
    for reg in registrations:
        if reg.created_at:
            local_time = reg.created_at.replace(tzinfo=timezone.utc).astimezone(pytz.timezone(current_user.timezone))
            timestamp_str = local_time.strftime('%Y-%m-%d %H:%M:%S')
        else:
            timestamp_str = ''
        cw.writerow([reg.name, reg.email, reg.phone, reg.status, timestamp_str, reg.reason or ''])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=registrations_{quiz.id}.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@q_events.route('/reject_registration/<int:registration_id>', methods=['POST'])
@login_required
def reject_registration(registration_id):
    try:
        registration = EventRegistration.query.get_or_404(registration_id)
        quiz = Quiz.query.get_or_404(registration.quiz_id)
        if quiz.user_id != current_user.id and not current_user.is_admin:
            return jsonify({'error': 'Unauthorized'}), 403
        reason = request.form.get('reason')
        if not reason:
            return jsonify({'error': 'Reason is required'}), 400
        registration.status = 'rejected'
        registration.reason = reason
        db.session.commit()
        
        flash(f'Registration for {registration.email} has been rejected.', 'success')
        
        msg = Message(
            subject=f'Payment Rejected - {quiz.title}',
            recipients=[registration.email],
            html=f"""
            <p>Your payment for {quiz.title} has been rejected.</p>
            <p>Reason: {reason}</p>
            <p>Please contact support for more information or re-register if applicable.</p>
            """
        )
        send_email_with_retry(msg)
        if socketio.server is not None:
            new_count = len([reg for reg in quiz.registrations if reg.status == 'verified'])
            socketio.emit('update_registration_count', {'quiz_id': quiz.id, 'count': new_count})
        else:
            logger.warning("SocketIO server not initialized, cannot emit event")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error in reject_registration: {str(e)}", exc_info=True)
        db.session.rollback()
        return jsonify({'error': f'Server error: {str(e)}'}), 500
    
@q_events.route('/verify_payment/<int:registration_id>', methods=['POST'])
@login_required
def verify_payment(registration_id):
    registration = EventRegistration.query.get_or_404(registration_id)
    quiz = Quiz.query.get_or_404(registration.quiz_id)
    if quiz.user_id != current_user.id and not current_user.is_admin:
        flash('You do not have permission to verify this payment.', 'danger')
        return redirect(url_for('events.event_dashboard', quiz_uuid=quiz.uuid))
    registration.status = 'verified'
    db.session.commit()
    try:
        msg = Message(
            subject=f'Payment Verified - {quiz.title}',
            recipients=[registration.email],
            html=f"""
            <p>Your payment for {quiz.title} has been verified!</p>
            <p>You can now take the quiz here: <a href="{url_for('quiz_taking.take_quiz', quiz_uuid=quiz.uuid, _external=True)}">{quiz.title}</a></p>
            """
        )
        send_email_with_retry(msg)
        if socketio.server is not None:
            new_count = len([reg for reg in quiz.registrations if reg.status == 'verified'])
            socketio.emit('update_registration_count', {'quiz_id': quiz.id, 'count': new_count})
        else:
            logger.warning("SocketIO server not initialized, cannot emit event")
        flash('Payment verified successfully!', 'success')
    except Exception as e:
        flash(f'Payment verified, but failed to send email: {str(e)}', 'warning')
    return redirect(url_for('events.event_dashboard', quiz_uuid=quiz.uuid))

# --- CHAT ROUTES AND SOCKETS ---

@q_events.route('/quiz/<string:quiz_uuid>/chat')
@login_required
def quiz_chat(quiz_uuid):
    quiz = Quiz.query.filter_by(uuid=quiz_uuid).first_or_404()
    
    is_creator = quiz.user_id == current_user.id
    is_verified_participant = EventRegistration.query.filter_by(
        quiz_id=quiz.id, user_id=current_user.id, status='verified'
    ).first() is not None
    
    if not (current_user.is_admin or is_creator or is_verified_participant):
        flash('You do not have permission to access this chat.', 'danger')
        return redirect(url_for('events.events'))

    messages = ChatMessage.query.filter_by(quiz_id=quiz.id).order_by(ChatMessage.timestamp.asc()).all()
    pinned_messages = ChatMessage.query.filter_by(quiz_id=quiz.id, is_pinned=True, is_deleted=False).order_by(ChatMessage.timestamp.desc()).all()
    
    user_role = get_user_role(current_user, quiz)

    return render_template(
        'quiz_chat.html', 
        quiz=quiz, 
        initial_messages=[msg.to_dict(current_user.id) for msg in messages],
        pinned_messages=[msg.to_dict(current_user.id) for msg in pinned_messages],
        user_role=user_role
    )

@q_events.route('/quiz/<string:quiz_uuid>/chat/upload', methods=['POST'])
@login_required
def upload_chat_file(quiz_uuid):
    quiz = Quiz.query.filter_by(uuid=quiz_uuid).first_or_404()
    user_role = get_user_role(current_user, quiz)

    if user_role not in ['admin', 'creator']:
        return jsonify({'error': 'You do not have permission to upload files.'}), 403

    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if file and allowed_file(file.filename, CHAT_ALLOWED_EXTENSIONS):
        filename = secure_filename(f"{uuid.uuid4()}_{file.filename}")
        filepath = os.path.join(CHAT_UPLOAD_FOLDER, filename)
        file.save(filepath)

        file_url = url_for('static', filename=f'uploads/chat/{filename}', _external=True)
        message_type = 'image' if allowed_file(filename, {'png', 'jpg', 'jpeg', 'gif'}) else 'file'
        
        new_message = ChatMessage(
            quiz_id=quiz.id, user_id=current_user.id, message_type=message_type,
            content=json.dumps({'url': file_url, 'name': file.filename})
        )
        db.session.add(new_message)
        db.session.commit()

        socketio.emit('new_message', {'message': new_message.to_dict(current_user.id)}, room=f'quiz_{quiz.id}')
        return jsonify({'success': True}), 201
    
    return jsonify({'error': 'File type not allowed'}), 400

@socketio.on('join_chat_room')
@login_required
def on_join(data):
    quiz_id = data.get('quiz_id')
    if not quiz_id: return
    
    room = f'quiz_{quiz_id}'
    join_room(room)

    if room not in online_users:
        online_users[room] = {}
    online_users[room][request.sid] = {'id': current_user.id, 'username': current_user.username}
    
    room_users = list(online_users[room].values())
    emit('update_online_users', {'users': room_users}, room=room)

@socketio.on('send_message')
@login_required
def on_send_message(data):
    quiz_id = data.get('quiz_id')
    quiz = db.session.get(Quiz, quiz_id)
    if not quiz: return

    if get_user_role(current_user, quiz) == 'participant':
        reg = EventRegistration.query.filter_by(quiz_id=quiz.id, user_id=current_user.id, status='verified').first()
        if not reg: return

    content = data.get('content')
    reply_to_id = data.get('reply_to_id')
    
    if content:
        chat_message = ChatMessage(
            quiz_id=quiz.id, user_id=current_user.id, content=content, reply_to_id=reply_to_id
        )
        db.session.add(chat_message)
        db.session.commit()
        emit('new_message', {'message': chat_message.to_dict(current_user.id)}, room=f'quiz_{quiz.id}')

@socketio.on('delete_message')
@login_required
def on_delete_message(data):
    message_id = data.get('message_id')
    message = db.session.get(ChatMessage, message_id)
    if not message: return

    user_role = get_user_role(current_user, message.quiz)
    if message.user_id == current_user.id or user_role in ['admin', 'creator']:
        message.is_deleted = True
        message.content = ""
        db.session.commit()
        emit('message_updated', {'message': message.to_dict(current_user.id)}, room=f'quiz_{message.quiz_id}')

@socketio.on('react_to_message')
@login_required
def on_react(data):
    message_id = data.get('message_id')
    emoji = data.get('emoji')
    message = db.session.get(ChatMessage, message_id)
    if not message or message.is_deleted: return

    existing_reaction = Reaction.query.filter_by(
        message_id=message_id, user_id=current_user.id, emoji=emoji
    ).first()

    if existing_reaction:
        db.session.delete(existing_reaction)
    else:
        db.session.add(Reaction(message_id=message_id, user_id=current_user.id, emoji=emoji))
    
    db.session.commit()
    updated_message = db.session.get(ChatMessage, message_id)
    emit('message_updated', {'message': updated_message.to_dict(current_user.id)}, room=f'quiz_{message.quiz_id}')

@socketio.on('pin_message')
@login_required
def on_pin_message(data):
    message_id = data.get('message_id')
    message = db.session.get(ChatMessage, message_id)
    if not message or message.is_deleted: return

    if get_user_role(current_user, message.quiz) in ['admin', 'creator']:
        message.is_pinned = not message.is_pinned
        db.session.commit()
        
        emit('message_updated', {'message': message.to_dict(current_user.id)}, room=f'quiz_{message.quiz_id}')
        
        pinned_messages = ChatMessage.query.filter_by(quiz_id=message.quiz_id, is_pinned=True, is_deleted=False).all()
        emit('pinned_list_updated', {
            'pinned_messages': [msg.to_dict(current_user.id) for msg in pinned_messages]
        }, room=f'quiz_{message.quiz_id}')

@socketio.on('create_poll')
@login_required
def on_create_poll(data):
    quiz_id = data.get('quiz_id')
    question = data.get('question')
    options = data.get('options', [])
    quiz = db.session.get(Quiz, quiz_id)
    if not quiz or not question or len(options) < 2: return

    if get_user_role(current_user, quiz) in ['admin', 'creator']:
        poll_message = ChatMessage(quiz_id=quiz_id, user_id=current_user.id, message_type='poll', content=question)
        db.session.add(poll_message)
        
        new_poll = Poll(chat_message=poll_message, question=question)
        db.session.add(new_poll)
        for option_text in options:
            if option_text.strip():
                db.session.add(PollOption(poll=new_poll, text=option_text.strip()))
        
        db.session.commit()
        emit('new_message', {'message': poll_message.to_dict(current_user.id)}, room=f'quiz_{quiz.id}')

@socketio.on('vote_on_poll')
@login_required
def on_vote_poll(data):
    poll_id = data.get('poll_id')
    option_id = data.get('option_id')
    poll = db.session.get(Poll, poll_id)
    if not poll: return

    existing_vote = PollVote.query.filter_by(poll_id=poll.id, user_id=current_user.id).first()
    if existing_vote:
        existing_vote.option_id = option_id
    else:
        db.session.add(PollVote(poll_id=poll.id, option_id=option_id, user_id=current_user.id))
    
    db.session.commit()
    
    poll_message = poll.chat_message
    emit('message_updated', {'message': poll_message.to_dict(current_user.id)}, room=f'quiz_{poll.chat_message.quiz_id}')

# Add these socket.io event handlers to events.py

@socketio.on('edit_message')
@login_required
def on_edit_message(data):
    message_id = data.get('message_id')
    content = data.get('content')
    message = db.session.get(ChatMessage, message_id)
    if not message: return

    user_role = get_user_role(current_user, message.quiz)
    if message.user_id == current_user.id or user_role in ['admin', 'creator']:
        message.content = content
        message.is_edited = True
        db.session.commit()
        emit('message_updated', {'message': message.to_dict(current_user.id)}, room=f'quiz_{message.quiz_id}')

@socketio.on('typing')
@login_required
def on_typing(data):
    quiz_id = data.get('quiz_id')
    room = f'quiz_{quiz_id}'
    
    if room in online_users:
        online_users[room][request.sid]['is_typing'] = True
        
        typing_users = {
            uid: user for uid, user in online_users[room].items() 
            if user.get('is_typing')
        }
        emit('user_typing', {'typingUsers': typing_users}, room=room)

@socketio.on('stop_typing')
@login_required
def on_stop_typing(data):
    quiz_id = data.get('quiz_id')
    room = f'quiz_{quiz_id}'
    
    if room in online_users and request.sid in online_users[room]:
        online_users[room][request.sid]['is_typing'] = False
        
        typing_users = {
            uid: user for uid, user in online_users[room].items() 
            if user.get('is_typing')
        }
        emit('user_stop_typing', {'typingUsers': typing_users}, room=room)