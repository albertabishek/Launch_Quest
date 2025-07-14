from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timezone
import uuid
import json
import pytz

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.Text, unique=True, nullable=False)
    email = db.Column(db.Text, unique=True, nullable=False)
    # UPDATED: Allow password to be nullable for OAuth-only users
    password_hash = db.Column(db.Text, nullable=True) 
    plan = db.Column(db.String(20), default='free')
    credits = db.Column(db.Integer, default=5)
    static_credits = db.Column(db.Integer, default=0)
    dynamic_credits = db.Column(db.Integer, default=0)
    last_reset_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    plan_expiration = db.Column(db.DateTime, nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    timezone = db.Column(db.String(50), default='UTC')

    # --- NEW: Column for Google OAuth ---
    google_id = db.Column(db.String(120), unique=True, nullable=True)

    @property
    def effective_plan(self):
        return self.plan or 'free'
    
    # Relationships
    quizzes = db.relationship('Quiz', backref='creator', lazy=True, cascade='all, delete-orphan')
    attempts = db.relationship('Attempt', backref='user', lazy=True, cascade='all, delete-orphan')
    chat_messages = db.relationship('ChatMessage', backref='user', lazy=True, cascade='all, delete-orphan')
    registrations = db.relationship('EventRegistration', backref='user', lazy=True, cascade='all, delete-orphan')

class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.Text, nullable=False)
    topic = db.Column(db.Text, nullable=False)
    language = db.Column(db.String(50), nullable=False)
    num_questions = db.Column(db.Integer, nullable=False)
    question_types = db.Column(db.Text, nullable=False)
    difficulty = db.Column(db.String(50), nullable=False)
    time_limit = db.Column(db.Integer, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    questions = db.Column(db.Text, nullable=True)
    generation_type = db.Column(db.String(10), nullable=False, default='static')
    quiz_type = db.Column(db.String(10), nullable=False, default='personal')
    max_users = db.Column(db.Integer, nullable=False, default=1)
    max_attempts = db.Column(db.Integer, nullable=False, default=1)
    interface_type = db.Column(db.String(10), default='default')
    background_color = db.Column(db.String(7), nullable=True)
    background_image = db.Column(db.String(255), nullable=True)
    logo = db.Column(db.String(255), nullable=True)
    tags = db.Column(db.Text, nullable=True)
    is_paid_event = db.Column(db.Boolean, default=False)
    fee_amount = db.Column(db.Integer, nullable=True)
    qr_code = db.Column(db.String(255), nullable=True)
    negative_marking = db.Column(db.Float, default=0.0)
    start_time = db.Column(db.DateTime, nullable=True)
    registration_end_time = db.Column(db.DateTime, nullable=True)
    password = db.Column(db.Text, nullable=True)
    num_winners = db.Column(db.Integer, nullable=True)
    winner_prizes = db.Column(db.Text, nullable=True)
    prize_currency = db.Column(db.String(3), nullable=True)

    registrations = db.relationship('EventRegistration', backref='quiz', lazy='dynamic')

    @property
    def registration_end_time_utc(self):
        """Return registration_end_time as a timezone-aware datetime in UTC."""
        return self.registration_end_time.replace(tzinfo=timezone.utc) if self.registration_end_time else None

    @property
    def start_time_utc(self):
        """Return start_time as a timezone-aware datetime in UTC."""
        return self.start_time.replace(tzinfo=timezone.utc) if self.start_time else None
    
    # Relationships
    attempts = db.relationship('Attempt', backref='quiz', lazy=True, cascade='all, delete-orphan')
    registrations = db.relationship('EventRegistration', backref='quiz', lazy=True, cascade='all, delete-orphan')
    chat_messages = db.relationship('ChatMessage', backref='quiz', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'uuid': self.uuid,
            'title': self.title,
            'topic': self.topic,
            'language': self.language,
            'num_questions': self.num_questions,
            'question_types': self.question_types.split(','),
            'difficulty': self.difficulty,
            'time_limit': self.time_limit,
            'user_id': self.user_id,
            'generation_type': self.generation_type,
            'quiz_type': self.quiz_type,
            'max_users': self.max_users,
            'max_attempts': self.max_attempts,
            'interface_type': self.interface_type,
            'background_color': self.background_color,
            'background_image': self.background_image,
            'logo': self.logo,
            'tags': self.tags,
            'is_paid_event': self.is_paid_event,
            'fee_amount': self.fee_amount,
            'qr_code': self.qr_code,
            'negative_marking': self.negative_marking,
            'start_time': self.start_time_utc.isoformat() if self.start_time_utc else None,
            'registration_end_time': self.registration_end_time_utc.isoformat() if self.registration_end_time_utc else None,
            'password': bool(self.password),
            'creator': {'username': self.creator.username},
            'num_winners': self.num_winners,
            'winner_prizes': self.winner_prizes.split(',') if self.winner_prizes else [],
            'prize_currency': self.prize_currency,
        }

class Attempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id', ondelete='CASCADE'), nullable=False)
    score = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    
    details = db.relationship('AttemptDetail', backref='attempt', lazy=True, cascade='all, delete-orphan')

class AttemptDetail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey('attempt.id', ondelete='CASCADE'), nullable=False)
    question_index = db.Column(db.Integer, nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    user_answer = db.Column(db.Text, nullable=True)
    correct_answer = db.Column(db.Text, nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False)
    is_multiple_answer = db.Column(db.Boolean, default=False)

class EventRegistration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    payment_screenshot = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    reason = db.Column(db.Text, nullable=True)

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.now(timezone.utc), index=True)
    
    message_type = db.Column(db.String(20), nullable=False, default='text') # text, image, file, poll
    content = db.Column(db.Text, nullable=False) # For text, links, or file paths/urls

    reply_to_id = db.Column(db.Integer, db.ForeignKey('chat_message.id'), nullable=True)
    is_edited = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False) # Soft delete
    is_pinned = db.Column(db.Boolean, default=False, index=True)

    # Relationships
    replies = db.relationship('ChatMessage', backref=db.backref('parent_message', remote_side=[id]), lazy='dynamic')
    poll = db.relationship('Poll', backref='chat_message', uselist=False, cascade='all, delete-orphan')
    reactions = db.relationship('Reaction', backref='chat_message', cascade='all, delete-orphan')

    def to_dict(self, current_user_id):
        # Helper to get reactions in a structured way
        reactions_data = {}
        for reaction in self.reactions:
            if reaction.emoji not in reactions_data:
                reactions_data[reaction.emoji] = []
            reactions_data[reaction.emoji].append(reaction.user.username)
        
        # Get parent message snippet if it's a reply
        parent_snippet = None
        if self.parent_message and not self.parent_message.is_deleted:
            parent_snippet = {
                'user': self.parent_message.user.username,
                'content': (self.parent_message.content[:40] + '...') if len(self.parent_message.content) > 40 else self.parent_message.content
            }
            
        return {
            'id': self.id,
            'quiz_id': self.quiz_id,
            'user': {
                'id': self.user.id,
                'username': self.user.username,
                'is_admin': self.user.is_admin,
                'is_creator': self.quiz.user_id == self.user.id
            },
            'timestamp': self.timestamp.replace(tzinfo=timezone.utc).isoformat() if self.timestamp else None,
            'message_type': self.message_type,
            'content': self.content if not self.is_deleted else "This message was deleted.",
            'reply_to_id': self.reply_to_id,
            'parent_snippet': parent_snippet,
            'is_edited': self.is_edited,
            'is_deleted': self.is_deleted,
            'is_pinned': self.is_pinned,
            'reactions': reactions_data,
            'poll': self.poll.to_dict(current_user_id) if self.poll else None,
            'is_own': self.user.id == current_user_id
        }

class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('chat_message.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)

    user = db.relationship('User')
    __table_args__ = (db.UniqueConstraint('message_id', 'user_id', 'emoji', name='_user_emoji_uc'),)

class Poll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('chat_message.id', ondelete='CASCADE'), nullable=False)
    question = db.Column(db.Text, nullable=False)
    
    options = db.relationship('PollOption', backref='poll', cascade='all, delete-orphan')

    def to_dict(self, user_id):
        user_vote = PollVote.query.filter_by(poll_id=self.id, user_id=user_id).first()
        options_data = [opt.to_dict() for opt in self.options]
        
        total_votes = sum(opt['vote_count'] for opt in options_data)
        
        return {
            'id': self.id,
            'question': self.question,
            'options': options_data,
            'user_voted_option': user_vote.option_id if user_vote else None,
            'total_votes': total_votes
        }

class PollOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id', ondelete='CASCADE'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    
    votes = db.relationship('PollVote', backref='option', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'text': self.text,
            'vote_count': len(self.votes)
        }

class PollVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id', ondelete='CASCADE'), nullable=False)
    option_id = db.Column(db.Integer, db.ForeignKey('poll_option.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    
    __table_args__ = (db.UniqueConstraint('poll_id', 'user_id', name='_user_poll_uc'),)