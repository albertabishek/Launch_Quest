from flask import Blueprint, jsonify, render_template, redirect, url_for, flash, request, session, make_response, current_app
from flask_login import login_required, current_user
from models import Quiz, Attempt, AttemptDetail, db, User, EventRegistration
from utils import reset_credits
from werkzeug.security import check_password_hash
from openai import OpenAI
import re
import json
from datetime import datetime, timezone
import pdfkit
from sqlalchemy import func, desc
import os
import base64
import pytz

quiz_taking = Blueprint('quiz_taking', __name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OpenAI API key not set in environment variables.")
client = OpenAI(api_key=OPENAI_API_KEY)

@quiz_taking.route('/take_quiz/<string:quiz_uuid>', methods=['GET', 'POST'])
@login_required
def take_quiz(quiz_uuid):
    reset_credits(current_user)
    quiz = Quiz.query.filter_by(uuid=quiz_uuid).first_or_404()
    creator = User.query.get(quiz.user_id)

    if quiz.password and not session.get(f'password_verified_{quiz_uuid}'):
        if request.method == 'POST':
            password = request.form.get('password')
            if check_password_hash(quiz.password, password):
                session[f'password_verified_{quiz_uuid}'] = True
                return redirect(url_for('quiz_taking.take_quiz', quiz_uuid=quiz_uuid))
            else:
                flash('Incorrect password', 'danger')
        return render_template('enter_password.html', quiz=quiz)
    
    if quiz.quiz_type == 'personal' and current_user.id != quiz.user_id:
        flash('This is a personal quiz and can only be taken by the creator.', 'danger')
        return redirect(url_for('quiz_management.my_quizzes'))

    if quiz.quiz_type == 'event' and quiz.is_paid_event:
        registration = EventRegistration.query.filter_by(quiz_id=quiz.id, user_id=current_user.id).first()
        if not registration or registration.status != 'verified':
            flash('You must register and verify payment to take this paid event quiz.', 'danger')
            return redirect(url_for('events.event_details', quiz_uuid=quiz_uuid))

    if quiz.quiz_type == 'event':
        has_attempted = Attempt.query.filter_by(user_id=current_user.id, quiz_id=quiz.id).first() is not None
        distinct_users = db.session.query(Attempt.user_id).filter_by(quiz_id=quiz.id).distinct().count()
        if not has_attempted and distinct_users >= quiz.max_users:
            flash('This event quiz has reached maximum participants', 'danger')
            return redirect(url_for('quiz_management.my_quizzes'))

    user_attempts = Attempt.query.filter_by(user_id=current_user.id, quiz_id=quiz.id).count()
    if user_attempts >= quiz.max_attempts:
        flash(f'You have reached the maximum attempts ({quiz.max_attempts}) for this quiz', 'danger')
        return redirect(url_for('quiz_management.my_quizzes'))

    if current_user.id == quiz.user_id:
        if creator.effective_plan == 'free' and creator.credits <= 0:
            flash('You have no credits left this month for the Free plan.', 'danger')
            return redirect(url_for('quiz_management.my_quizzes'))
        elif creator.effective_plan == 'pro' and creator.credits <= 0:
            flash('You have no credits left this month for the Pro plan.', 'danger')
            return redirect(url_for('quiz_management.my_quizzes'))
        elif creator.effective_plan == 'premium':
            if quiz.generation_type == 'static' and creator.static_credits <= 0:
                flash('You have no static quiz credits left this month for the Premium plan.', 'danger')
                return redirect(url_for('quiz_management.my_quizzes'))
            elif quiz.generation_type == 'dynamic' and creator.dynamic_credits <= 0:
                flash('You have no dynamic quiz credits left this month for the Premium plan.', 'danger')
                return redirect(url_for('quiz_management.my_quizzes'))
    else:
        if creator.effective_plan == 'free':
            flash('Free plan users cannot share quizzes.', 'danger')
            return redirect(url_for('quiz_management.my_quizzes'))
        elif creator.effective_plan == 'pro' and creator.credits <= 0:
            flash('The creator has no credits left this month for the Pro plan.', 'danger')
            return redirect(url_for('quiz_management.my_quizzes'))
        elif creator.effective_plan == 'premium':
            if quiz.generation_type == 'static' and creator.static_credits <= 0:
                flash('The creator has no static quiz credits left this month for the Premium plan.', 'danger')
                return redirect(url_for('quiz_management.my_quizzes'))
            elif quiz.generation_type == 'dynamic' and creator.dynamic_credits <= 0:
                flash('The creator has no dynamic quiz credits left this month for the Premium plan.', 'danger')
                return redirect(url_for('quiz_management.my_quizzes'))

    prompt = f"Generate a quiz with the following details:\n"
    prompt += f"- Title: {quiz.title}\n- Topic: {quiz.topic}\n- Language: {quiz.language}\n- Number of questions: {quiz.num_questions}\n"
    prompt += f"- Question types: {quiz.question_types}\n- Difficulty: {quiz.difficulty}\n- Time limit: {quiz.time_limit if quiz.time_limit else 'None'} minutes\n"
    prompt += "Provide questions in JSON format with a 'questions' key containing a list of questions. Each question must have 'type', 'question', 'options' (for 'multiple-choice' include at least 4 options, for 'true-false' include ['True', 'False']), and 'answer'."

    if quiz.generation_type == 'static':
        if not quiz.questions:
            try:
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "system", "content": "You are a precise quiz generator."}, {"role": "user", "content": prompt}]
                )
                response_text = response.choices[0].message.content
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    quiz_data = json.loads(json_match.group(0))
                else:
                    raise ValueError("No valid JSON found in response")
                quiz.questions = json.dumps(quiz_data)
                db.session.commit()
            except Exception as e:
                flash(f'Failed to generate quiz questions: {str(e)}', 'danger')
                return redirect(url_for('quiz_management.my_quizzes'))
        quiz_data = json.loads(quiz.questions)
    else:
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages= [{"role": "system", "content": "You are a precise quiz generator."}, {"role": "user", "content": prompt}]
            )
            response_text = response.choices[0].message.content
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                quiz_data = json.loads(json_match.group(0))
            else:
                raise ValueError("No valid JSON found in response")
            session['dynamic_questions'] = quiz_data
        except Exception as e:
            flash(f'Failed to generate quiz questions: {str(e)}', 'danger')
            return redirect(url_for('quiz_management.my_quizzes'))
    
    if quiz.quiz_type == 'event' and quiz.start_time_utc and quiz.start_time_utc > datetime.now(timezone.utc):
        flash('This quiz has not started yet', 'danger')
        return redirect(url_for('events.events'))
    
    questions = []
    for q in quiz_data.get('questions', []):
        if 'type' not in q or 'question' not in q:
            continue
        question = {'type': q['type'], 'question': q['question']}
        if q['type'] == 'multiple-choice':
            question['options'] = q.get('options', [])
            answer = q.get('answer', [])
            question['is_multiple_answer'] = isinstance(answer, list) and len(answer) > 1
        elif q['type'] == 'true-false':
            question['options'] = q.get('options', ['True', 'False'])
        questions.append(question)

    if not questions:
        flash('No valid questions generated for this quiz.', 'danger')
        return redirect(url_for('quiz_management.my_quizzes'))

    session['quiz_uuid'] = quiz.uuid
    return render_template('quiz_taking.html', quiz=quiz, questions=questions, time_limit=quiz.time_limit)

@quiz_taking.route('/submit_quiz', methods=['POST'])
@login_required
def submit_quiz():
    quiz_uuid = session.get('quiz_uuid')
    if not quiz_uuid:
        flash('No quiz found.', 'danger')
        return redirect(url_for('quiz_management.my_quizzes'))
    quiz = Quiz.query.filter_by(uuid=quiz_uuid).first_or_404()
    creator = User.query.get(quiz.user_id)

    if quiz.generation_type == 'static':
        if not quiz.questions:
            flash('Quiz questions not found.', 'danger')
            return redirect(url_for('quiz_management.my_quizzes'))
        quiz_data = json.loads(quiz.questions)
    else:
        quiz_data = session.get('dynamic_questions')
        if not quiz_data:
            flash('Quiz questions not found.', 'danger')
            return redirect(url_for('quiz_management.my_quizzes'))

    questions = quiz_data.get('questions', [])
    score = 0.0
    total = 0
    wrong_answers = 0
    results = []
    for i, q in enumerate(questions):
        if 'type' not in q or 'question' not in q or 'answer' not in q:
            continue
        if q['type'] == 'multiple-choice' and 'options' not in q:
            continue
        if q['type'] == 'essay':
            continue
        total += 1
        user_answer = None
        is_correct = False
        if q['type'] == 'multiple-choice':
            answer = q.get('answer', [])
            if isinstance(answer, list) and len(answer) > 1:
                user_answer_raw = request.form.getlist(f'answer_{i}[]')
                user_answer_lower = [ans.strip().lower() for ans in user_answer_raw]
                correct_answer_lower = [a.strip().lower() for a in answer]
                is_correct = set(user_answer_lower) == set(correct_answer_lower)
                user_answer = user_answer_raw if user_answer_raw else []
                correct_answer = answer
                is_multiple_answer = True
            else:
                user_answer = request.form.get(f'answer_{i}', '')
                user_answer_lower = user_answer.strip().lower()
                correct_answer = answer[0] if isinstance(answer, list) else answer
                correct_answer_lower = correct_answer.strip().lower()
                is_correct = user_answer_lower == correct_answer_lower
                correct_answer = correct_answer
                is_multiple_answer = False
        elif q['type'] == 'true-false':
            user_answer = request.form.get(f'answer_{i}', '')
            user_answer_lower = user_answer.strip().lower()
            correct_answer = str(q.get('answer', '')).strip().lower()
            is_correct = user_answer_lower == correct_answer
            correct_answer = q.get('answer', '')
            is_multiple_answer = False
        elif q['type'] == 'short-answer':
            user_answer = request.form.get(f'answer_{i}', '').strip()
            user_answer_lower = user_answer.lower()
            correct_answer = q.get('answer', '').strip().lower()
            is_correct = user_answer_lower == correct_answer
            correct_answer = q.get('answer', '')
            is_multiple_answer = False
        if is_correct:
            score += 1.0
        else:
            wrong_answers += 1
        results.append({
            'question': q['question'],
            'type': q['type'],
            'options': q.get('options', ['True', 'False'] if q['type'] == 'true-false' else []),
            'user_answer': user_answer,
            'correct_answer': correct_answer,
            'is_correct': is_correct,
            'is_multiple_answer': is_multiple_answer
        })

    negative_mark = quiz.negative_marking or 0.0
    score = max(0, score - (wrong_answers * negative_mark))

    attempt = Attempt(user_id=current_user.id, quiz_id=quiz.id, score=score, timestamp=datetime.now(timezone.utc))
    db.session.add(attempt)
    db.session.commit()

    for i, result in enumerate(results):
        detail = AttemptDetail(
            attempt_id=attempt.id,
            question_index=i,
            question_text=result['question'],
            user_answer=json.dumps(result['user_answer']) if result['user_answer'] else None,
            correct_answer=json.dumps(result['correct_answer']),
            is_correct=result['is_correct'],
            is_multiple_answer=result.get('is_multiple_answer', False)
        )
        db.session.add(detail)

    if current_user.id == quiz.user_id:
        if current_user.effective_plan == 'free':
            current_user.credits -= 1
        elif current_user.effective_plan == 'pro':
            current_user.credits -= 1
        elif current_user.effective_plan == 'premium':
            if quiz.generation_type == 'static':
                current_user.static_credits -= 1
            else:
                current_user.dynamic_credits -= 1
    else:
        if creator.effective_plan == 'pro':
            creator.credits -= 1
        elif creator.effective_plan == 'premium':
            if quiz.generation_type == 'static':
                creator.static_credits -= 1
            else:
                creator.dynamic_credits -= 1
    db.session.commit()

    if quiz.generation_type == 'dynamic':
        session.pop('dynamic_questions', None)
    return render_template('quiz_results.html', quiz=quiz, results=results, score=score, total=total)

@quiz_taking.route('/leaderboard/<string:quiz_uuid>', methods=['GET', 'POST'])
@login_required
def leaderboard(quiz_uuid):
    quiz = Quiz.query.filter_by(uuid=quiz_uuid).first_or_404()

    date_filter = request.form.get('date_filter') if request.method == 'POST' else request.args.get('date_filter')
    query = db.session.query(
        Attempt.user_id,
        func.max(Attempt.score).label('max_score'),
        func.min(Attempt.timestamp).label('min_timestamp'),
        User.username
    ).join(User, User.id == Attempt.user_id).filter(Attempt.quiz_id == quiz.id).group_by(Attempt.user_id, User.username)

    if date_filter and current_user.is_admin:
        try:
            filter_date = datetime.strptime(date_filter, '%Y-%m-%d')
            query = query.filter(db.func.date(Attempt.timestamp) == filter_date)
        except ValueError:
            flash('Invalid date format. Please use YYYY-MM-DD.', 'danger')

    attempts = query.order_by(desc('max_score'), 'min_timestamp', 'username').all()

    ranked_attempts = []
    rank = 1
    for i, attempt in enumerate(attempts):
        if i > 0 and (attempt.max_score != attempts[i-1].max_score or attempt.min_timestamp != attempts[i-1].min_timestamp):
            rank = i + 1
        ranked_attempts.append({
            'rank': rank,
            'username': attempt.username,
            'score': attempt.max_score,
            'timestamp': attempt.min_timestamp
        })
    prizes = []
    if quiz.winner_prizes:
        prize_amounts = quiz.winner_prizes.split(',')
        for i, attempt in enumerate(ranked_attempts):
            prize = None
            if i < len(prize_amounts):
                prize = {
                    'amount': prize_amounts[i],
                    'currency': quiz.prize_currency
                }
            prizes.append(prize)

    return render_template('leaderboard.html', quiz=quiz, attempts=ranked_attempts, is_admin=current_user.is_admin, date_filter=date_filter, prizes=prizes)

@quiz_taking.route('/download_results/<string:quiz_uuid>')
@login_required
def download_results(quiz_uuid):
    quiz = Quiz.query.filter_by(uuid=quiz_uuid).first_or_404()
    if quiz.user_id != current_user.id and not current_user.is_admin:
        flash('You do not have permission to download this quiz result.', 'danger')
        return redirect(url_for('quiz_management.my_quizzes'))
    
    attempt = Attempt.query.filter_by(user_id=current_user.id, quiz_id=quiz.id).order_by(Attempt.timestamp.desc()).first()
    if not attempt:
        flash('No results found for this quiz.', 'danger')
        return redirect(url_for('quiz_management.my_quizzes'))
    
    details = AttemptDetail.query.filter_by(attempt_id=attempt.id).order_by(AttemptDetail.question_index).all()
    results = [{
        'question': detail.question_text,
        'user_answer': json.loads(detail.user_answer) if detail.user_answer else None,
        'correct_answer': json.loads(detail.correct_answer),
        'is_correct': detail.is_correct,
        'is_multiple_answer': detail.is_multiple_answer
    } for detail in details]
    
    logo_data = None
    mime_type = None
    if quiz.interface_type == 'custom' and quiz.logo:
        logo_path = os.path.join(current_app.root_path, 'static', 'uploads', quiz.logo)
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                logo_data = base64.b64encode(f.read()).decode('utf-8')
            extension = os.path.splitext(quiz.logo)[1].lower()
            mime_type = {'jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif'}.get(extension, 'image/png')
    
    rendered = render_template('quiz_results_pdf.html',
                               quiz=quiz,
                               results=results,
                               score=attempt.score,
                               total=len(results),
                               current_user=current_user,
                               logo_data=logo_data,
                               mime_type=mime_type,
                               current_time=datetime.now(timezone.utc))
    
    options = {
        'page-size': 'A4',
        'margin-top': '0.75in', 'margin-right': '0.75in',
        'margin-bottom': '0.75in', 'margin-left': '0.75in',
        'encoding': "UTF-8",
        'enable-local-file-access': None
    }
    
    try:
        pdf = pdfkit.from_string(rendered, False, options=options)
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=quiz_results_{quiz.id}.pdf'
        return response
    except Exception as e:
        flash(f'Failed to generate PDF: {str(e)}', 'danger')
        return redirect(url_for('quiz_management.my_quizzes'))
    
@quiz_taking.route('/verify_password/<string:quiz_uuid>', methods=['POST'])
@login_required
def verify_password(quiz_uuid):
    quiz = Quiz.query.filter_by(uuid=quiz_uuid).first_or_404()
    if not quiz.password:
        return jsonify({'success': True})
    data = request.get_json()
    password = data.get('password')
    if check_password_hash(quiz.password, password):
        session[f'password_verified_{quiz_uuid}'] = True
        return jsonify({'success': True})
    return jsonify({'success': False}), 403