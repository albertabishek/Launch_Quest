from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import Quiz, db, User, EventRegistration, Attempt
from forms import QuizForm
from utils import reset_credits, get_attempts_this_month
from werkzeug.security import generate_password_hash
import os
from werkzeug.utils import secure_filename
import uuid
from sqlalchemy import func
import pytz  # Added for time zone handling

quiz_management = Blueprint('quiz_management', __name__)

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static', 'uploads')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@quiz_management.route('/my_quizzes')
@login_required
def my_quizzes():
    reset_credits(current_user)
    
    owned_quizzes = Quiz.query.filter_by(user_id=current_user.id).order_by(Quiz.id.desc()).all()
    user_registrations = EventRegistration.query.filter_by(user_id=current_user.id).all()
    
    registered_quizzes = [reg.quiz for reg in user_registrations if reg.quiz]
    registered_quizzes_registrations = {reg.quiz.id: reg for reg in user_registrations if reg.quiz}
    
    all_quizzes = owned_quizzes + registered_quizzes
    now = datetime.now(timezone.utc)

    for quiz in all_quizzes:
        quiz.registered_count = len([reg for reg in quiz.registrations if reg.status == 'verified'])
        registration_end_time_utc = (
            quiz.registration_end_time.replace(tzinfo=timezone.utc) 
            if quiz.registration_end_time else None
        )
        quiz.registration_closed = (
            (registration_end_time_utc and registration_end_time_utc < now) or
            (quiz.max_users and quiz.registered_count >= quiz.max_users)
        )

    quizzes_data = [quiz.to_dict() for quiz in owned_quizzes]
    highest_scores = {quiz.id: db.session.query(func.max(Attempt.score)).filter_by(user_id=current_user.id, quiz_id=quiz.id).scalar() for quiz in all_quizzes}
    attempts_this_month = get_attempts_this_month(current_user.id)
    static_attempts = get_attempts_this_month(current_user.id, 'static')
    dynamic_attempts = get_attempts_this_month(current_user.id, 'dynamic')
    registrations = {quiz.id: EventRegistration.query.filter_by(quiz_id=quiz.id, user_id=current_user.id).first() for quiz in owned_quizzes}
    user_attempts = {quiz.id: Attempt.query.filter_by(user_id=current_user.id, quiz_id=quiz.id).count() for quiz in all_quizzes}
    reg_counts = {quiz.id: quiz.registered_count for quiz in all_quizzes}

    form = QuizForm()
    is_free_plan = current_user.effective_plan == 'free'
    if is_free_plan:
        form.question_types.choices = [('multiple-choice', 'Multiple Choice'), ('true-false', 'True/False')]
        form.generation_type.choices = [('static', 'Same Quiz Each Time')]
    else:
        form.question_types.choices = [
            ('multiple-choice', 'Multiple Choice'),
            ('short-answer', 'Short Answer'),
            ('essay', 'Essay'),
            ('true-false', 'True/False')
        ]
        form.generation_type.choices = [('static', 'Same Quiz Each Time'), ('dynamic', 'New Quiz Each Time')]

    return render_template(
        'my_quizzes.html',
        form=form,
        is_free_plan=is_free_plan,
        owned_quizzes=owned_quizzes,
        registered_quizzes=registered_quizzes,
        registered_quizzes_registrations=registered_quizzes_registrations,
        quizzes_data=quizzes_data,
        highest_scores=highest_scores,
        attempts_this_month=attempts_this_month,
        static_attempts=static_attempts,
        dynamic_attempts=dynamic_attempts,
        registrations=registrations,
        user_attempts=user_attempts,
        reg_counts=reg_counts,
        current_time=now
    )

@quiz_management.route('/generate_quiz', methods=['GET', 'POST'])
@login_required
def generate_quiz():
    reset_credits(current_user)
    form = QuizForm()
    is_free_plan = current_user.effective_plan == 'free'

    if is_free_plan:
        form.question_types.choices = [('multiple-choice', 'Multiple Choice'), ('true-false', 'True/False')]
        form.generation_type.choices = [('static', 'Same Quiz Each Time')]
    else:
        form.question_types.choices = [
            ('multiple-choice', 'Multiple Choice'), ('short-answer', 'Short Answer'),
            ('essay', 'Essay'), ('true-false', 'True/False')
        ]
        form.generation_type.choices = [('static', 'Same Quiz Each Time'), ('dynamic', 'New Quiz Each Time')]

    if request.method == 'GET' and is_free_plan:
        form.quiz_type.data = 'personal'
        form.interface_type.data = 'default'

    if form.validate_on_submit():
        if is_free_plan and (form.quiz_type.data == 'event' or form.interface_type.data == 'custom'):
            flash('Your plan does not support Event Quizzes or Custom Interfaces. Please upgrade.', 'danger')
            return redirect(url_for('quiz_management.generate_quiz'))

        user_tz = pytz.timezone(current_user.timezone if current_user.timezone in pytz.all_timezones else 'UTC')
        start_time_utc = None
        registration_end_time_utc = None

        if form.quiz_type.data == 'event':
            if form.start_time.data:
                # Localize the naive datetime from the form to user's timezone
                local_start_time = user_tz.localize(form.start_time.data)
                # Convert to UTC and remove tzinfo for storage
                start_time_utc = local_start_time.astimezone(pytz.utc).replace(tzinfo=None)

            if form.registration_end_time.data:
                # Localize the naive datetime from the form to user's timezone
                local_reg_end_time = user_tz.localize(form.registration_end_time.data)
                # Convert to UTC and remove tzinfo for storage
                registration_end_time_utc = local_reg_end_time.astimezone(pytz.utc).replace(tzinfo=None)
                
        new_quiz = Quiz(
            title=form.title.data,
            topic=form.topic.data,
            language=form.language.data,
            num_questions=int(form.num_questions.data),
            question_types=','.join(form.question_types.data),
            difficulty=form.difficulty.data,
            time_limit=form.time_limit.data if form.time_limit.data and form.time_limit.data > 0 else None,
            user_id=current_user.id,
            generation_type=form.generation_type.data if not is_free_plan else 'static',
            quiz_type=form.quiz_type.data,
            max_users=1 if form.quiz_type.data == 'personal' else form.max_users.data,
            max_attempts=form.max_attempts.data,
            interface_type=form.interface_type.data,
            background_color=form.background_color.data if form.interface_type.data == 'custom' else None,
            tags=form.tags.data,
            is_paid_event=form.is_paid_event.data and form.quiz_type.data == 'event',
            fee_amount=form.fee_amount.data if form.is_paid_event.data and form.quiz_type.data == 'event' else None,
            negative_marking=form.negative_marking.data or 0,
            start_time=start_time_utc,
            registration_end_time=registration_end_time_utc,
            password=generate_password_hash(form.password.data) if form.password.data else None,
            num_winners=form.num_winners.data if form.quiz_type.data == 'event' and form.is_paid_event.data else None,
            winner_prizes=form.winner_prizes.data if form.quiz_type.data == 'event' and form.is_paid_event.data else None,
            prize_currency=form.prize_currency.data if form.quiz_type.data == 'event' and form.is_paid_event.data else None
        )
 
        if form.interface_type.data == 'custom':
            if form.background_image.data and allowed_file(form.background_image.data.filename):
                filename = secure_filename(f"{uuid.uuid4()}_{form.background_image.data.filename}")
                form.background_image.data.save(os.path.join(UPLOAD_FOLDER, filename))
                new_quiz.background_image = filename
            if form.logo.data and allowed_file(form.logo.data.filename):
                filename = secure_filename(f"{uuid.uuid4()}_{form.logo.data.filename}")
                form.logo.data.save(os.path.join(UPLOAD_FOLDER, filename))
                new_quiz.logo = filename
        if form.is_paid_event.data and form.quiz_type.data == 'event' and form.qr_code.data and allowed_file(form.qr_code.data.filename):
            filename = secure_filename(f"{uuid.uuid4()}_{form.qr_code.data.filename}")
            form.qr_code.data.save(os.path.join(UPLOAD_FOLDER, filename))
            new_quiz.qr_code = filename

        db.session.add(new_quiz)
        db.session.commit()
        flash('Quiz created successfully!', 'success')
        return redirect(url_for('quiz_management.my_quizzes'))
        
    return render_template('generate_quiz.html', form=form, is_free_plan=is_free_plan)

@quiz_management.route('/edit_quiz', methods=['POST'])
@login_required
def edit_quiz():
    quiz_id = request.form.get('quiz_id')
    quiz = Quiz.query.get_or_404(quiz_id)

    if quiz.user_id != current_user.id and not current_user.is_admin:
        flash('You do not have permission to edit this quiz.', 'danger')
        return redirect(url_for('quiz_management.my_quizzes'))

    form = QuizForm(request.form)
    is_free_plan = current_user.effective_plan == 'free'

    if is_free_plan:
        form.question_types.choices = [('multiple-choice', 'Multiple Choice'), ('true-false', 'True/False')]
        form.generation_type.choices = [('static', 'Same Quiz Each Time')]
    else:
        form.question_types.choices = [
            ('multiple-choice', 'Multiple Choice'), ('short-answer', 'Short Answer'),
            ('essay', 'Essay'), ('true-false', 'True/False')
        ]
        form.generation_type.choices = [('static', 'Same Quiz Each Time'), ('dynamic', 'New Quiz Each Time')]

    is_paid_event_checked = 'is_paid_event' in request.form

    if form.validate():
        if is_free_plan and form.generation_type.data == 'dynamic':
            flash('Free plan users cannot set quizzes to dynamic generation.', 'danger')
            return redirect(url_for('quiz_management.my_quizzes'))

        user_tz = pytz.timezone(current_user.timezone if current_user.timezone in pytz.all_timezones else 'UTC')
        if quiz.quiz_type == 'event':
            if form.start_time.data:
                local_start_time = user_tz.localize(form.start_time.data)
                quiz.start_time = local_start_time.astimezone(pytz.utc).replace(tzinfo=None)
            if form.registration_end_time.data:
                local_reg_end_time = user_tz.localize(form.registration_end_time.data)
                quiz.registration_end_time = local_reg_end_time.astimezone(pytz.utc).replace(tzinfo=None)


        quiz.title = form.title.data
        quiz.topic = form.topic.data
        quiz.language = form.language.data
        quiz.num_questions = int(form.num_questions.data)
        quiz.question_types = ','.join(form.question_types.data)
        quiz.difficulty = form.difficulty.data
        quiz.time_limit = form.time_limit.data if form.time_limit.data and form.time_limit.data > 0 else None
        quiz.generation_type = form.generation_type.data
        quiz.quiz_type = form.quiz_type.data
        quiz.max_users = 1 if quiz.quiz_type == 'personal' else form.max_users.data
        quiz.max_attempts = form.max_attempts.data
        quiz.interface_type = form.interface_type.data
        quiz.tags = form.tags.data
        quiz.negative_marking = form.negative_marking.data or 0
        
        password = form.password.data
        if password:
            quiz.password = generate_password_hash(password)

        if quiz.quiz_type == 'event':
            quiz.is_paid_event = is_paid_event_checked
            if quiz.is_paid_event:
                quiz.fee_amount = form.fee_amount.data
                quiz.num_winners = form.num_winners.data
                quiz.winner_prizes = form.winner_prizes.data
                quiz.prize_currency = form.prize_currency.data
                
                # QR Code handling: Use existing or new upload
                if 'qr_code' in request.files and request.files['qr_code'].filename != '':
                    if allowed_file(request.files['qr_code'].filename):
                        filename = secure_filename(f"{uuid.uuid4()}_{request.files['qr_code'].filename}")
                        request.files['qr_code'].save(os.path.join(UPLOAD_FOLDER, filename))
                        quiz.qr_code = filename
                elif not quiz.qr_code:
                    flash('QR code image is required for paid events.', 'danger')
                    return redirect(url_for('quiz_management.my_quizzes'))
            else:
                quiz.fee_amount = None
                quiz.num_winners = None
                quiz.winner_prizes = None
                quiz.prize_currency = None
                quiz.qr_code = None
        else:
            quiz.is_paid_event = False
            quiz.qr_code = None

        if quiz.interface_type == 'custom':
            quiz.background_color = form.background_color.data
            if 'background_image' in request.files and request.files['background_image'].filename != '':
                if allowed_file(request.files['background_image'].filename):
                    filename = secure_filename(f"{uuid.uuid4()}_{request.files['background_image'].filename}")
                    request.files['background_image'].save(os.path.join(UPLOAD_FOLDER, filename))
                    quiz.background_image = filename
            if 'logo' in request.files and request.files['logo'].filename != '':
                if allowed_file(request.files['logo'].filename):
                    filename = secure_filename(f"{uuid.uuid4()}_{request.files['logo'].filename}")
                    request.files['logo'].save(os.path.join(UPLOAD_FOLDER, filename))
                    quiz.logo = filename
        else:
            quiz.background_color = None
            quiz.background_image = None
            quiz.logo = None

        quiz.questions = None  # Force regeneration on next take
        db.session.commit()
        flash('Quiz updated successfully!', 'success')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Error in {getattr(form, field).label.text}: {error}", 'danger')

    return redirect(url_for('quiz_management.my_quizzes'))

@quiz_management.route('/delete_quiz/<int:quiz_id>', methods=['POST'])
@login_required
def delete_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    if quiz.user_id != current_user.id and not current_user.is_admin:
        flash('You do not have permission to delete this quiz.', 'danger')
        return redirect(url_for('quiz_management.my_quizzes'))
    db.session.delete(quiz)
    db.session.commit()
    flash('Quiz deleted successfully!', 'success')
    return redirect(url_for('quiz_management.my_quizzes'))

@quiz_management.route('/embed_quiz/<string:quiz_uuid>')
def embed_quiz(quiz_uuid):
    quiz = Quiz.query.filter_by(uuid=quiz_uuid).first_or_404()
    return render_template('embed_quiz.html', quiz=quiz)