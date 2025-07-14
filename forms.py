from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, SelectField, IntegerField, SubmitField, SelectMultipleField, widgets, BooleanField, PasswordField
from wtforms.fields import DateTimeLocalField
from wtforms.validators import DataRequired, Email, NumberRange, ValidationError, Optional, EqualTo
from datetime import datetime, timezone

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = StringField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Login')

class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = StringField('Password', validators=[DataRequired()])
    timezone = SelectField('Time Zone', choices=[
        ('UTC', 'UTC'),
        ('Asia/Kolkata', 'IST (India)'),
        ('America/New_York', 'EST (New York)'),
        ('Europe/London', 'GMT (London)'),
        # Add more time zones as needed
    ], default='UTC', validators=[DataRequired()])
    submit = SubmitField('Register')

# --- NEW: Form for completing OAuth registration ---
class CompleteAccountForm(FlaskForm):
    password = PasswordField('Password', validators=[
        DataRequired(message="A password is required."),
        EqualTo('confirm', message='Passwords must match.')
    ])
    confirm = PasswordField('Repeat Password')
    timezone = SelectField('Time Zone', choices=[
        ('UTC', 'UTC'),
        ('Asia/Kolkata', 'IST (India)'),
        ('America/New_York', 'EST (New York)'),
        ('Europe/London', 'GMT (London)'),
        # Add more time zones as needed
    ], default='UTC', validators=[DataRequired()])
    submit = SubmitField('Complete Account Setup')

class QuizForm(FlaskForm):
    title = StringField('Quiz Title', validators=[DataRequired()])
    topic = StringField('Topic', validators=[DataRequired()])
    language = SelectField(
        'Language',
        choices=[('en', 'English'), ('es', 'Spanish'), ('fr', 'French')],
        validators=[DataRequired()]
    )
    num_questions = SelectField(
        'Number of Questions',
        choices=[(str(i), f"{i} Questions") for i in [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60]],
        validators=[DataRequired()]
    )
    question_types = SelectMultipleField(
        'Question Types',
        widget=widgets.ListWidget(prefix_label=False),
        option_widget=widgets.CheckboxInput(),
        description='Select at least one question type.'
    )
    difficulty = SelectField(
        'Difficulty Level',
        choices=[('easy', 'Easy'), ('medium', 'Medium'), ('hard', 'Hard')],
        validators=[DataRequired()]
    )
    time_limit = IntegerField(
        'Time Limit (minutes)',
        validators=[NumberRange(min=0)],
        default=0
    )
    generation_type = SelectField(
        'Quiz Generation Type',
        choices=[('static', 'Same Quiz Each Time'), ('dynamic', 'New Quiz Each Time')],
        default='static'
    )
    quiz_type = SelectField(
        'Quiz Type',
        choices=[('personal', 'Personal Quiz'), ('event', 'Event Quiz')],
        default='personal',
        validators=[DataRequired()]
    )
    max_users = IntegerField(
        'Maximum Users',
        validators=[NumberRange(min=1)],
        default=1
    )
    max_attempts = IntegerField(
        'Attempts Per User',
        validators=[NumberRange(min=1)],
        default=1
    )
    interface_type = SelectField(
        'Interface Type',
        choices=[('default', 'Default'), ('custom', 'Custom')],
        default='default'
    )
    background_color = StringField('Background Color')
    background_image = FileField('Background Image')
    logo = FileField('Logo')
    tags = StringField('Tags', description='Enter tags separated by commas (e.g., math, science)')
    is_paid_event = BooleanField('Paid Event?')
    fee_amount = IntegerField('Fee Amount', validators=[NumberRange(min=0)], default=0)
    qr_code = FileField('QR Code Image')
    negative_marking = IntegerField('Negative Marking per Wrong Answer', validators=[NumberRange(min=0)], default=0)
    start_time = DateTimeLocalField('Start Time', format='%Y-%m-%dT%H:%M', validators=[Optional()])
    registration_end_time = DateTimeLocalField('Registration End Time', format='%Y-%m-%dT%H:%M', validators=[Optional()])
    password = PasswordField('Password', validators=[Optional()])
    num_winners = IntegerField(
        'Number of Winners',
        validators=[NumberRange(min=1)],
        default=1
    )
    winner_prizes = StringField(
        'Winner Prizes (comma separated)',
        description='Enter prize amounts separated by commas (e.g., 1000,500,200)'
    )
    prize_currency = SelectField(
        'Prize Currency',
        choices=[('INR', 'Indian Rupee (₹)'), ('USD', 'US Dollar ($)'), ('EUR', 'Euro (€)')],
        default='INR'
    )
    submit = SubmitField('Generate Quiz')

    def validate_question_types(self, field):
        if not field.data or len(field.data) == 0:
            raise ValidationError("Please select at least one question type.")

    def validate_max_users(self, field):
        if self.quiz_type.data == 'event' and field.data < 2:
            raise ValidationError("Event quizzes must allow at least 2 users")

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators=extra_validators):
            return False
        if self.quiz_type.data == 'event':
            if not self.start_time.data:
                self.start_time.errors.append('Start time is required for event quizzes.')
                return False
            if not self.registration_end_time.data:
                self.registration_end_time.errors.append('Registration end time is required for event quizzes.')
                return False
            # Make naive datetimes offset-aware by assuming they are in UTC
            start_time_utc = self.start_time.data.replace(tzinfo=timezone.utc)
            registration_end_time_utc = self.registration_end_time.data.replace(tzinfo=timezone.utc)
            now_utc = datetime.now(timezone.utc)
            if start_time_utc < now_utc:
                self.start_time.errors.append('Start time must be in the future (UTC).')
                return False
            if registration_end_time_utc >= start_time_utc:
                self.registration_end_time.errors.append('Registration end time must be before start time (UTC).')
                return False
        if self.is_paid_event.data:
            if self.fee_amount.data is None or self.fee_amount.data <= 0:
                self.fee_amount.errors.append('Fee amount must be a positive integer for paid events.')
                return False
        return True

    def validate_winner_prizes(self, field):
        if self.is_paid_event.data:
            if not field.data:
                raise ValidationError("Please enter prize amounts for winners.")
            prizes = field.data.split(',')
            if len(prizes) != self.num_winners.data:
                raise ValidationError(f"Number of prizes must match number of winners ({self.num_winners.data})")
            try:
                for prize in prizes:
                    if not prize.strip().isdigit():
                        raise ValueError
            except ValueError:
                raise ValidationError("Prizes must be comma-separated numbers")