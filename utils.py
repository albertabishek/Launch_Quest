from models import db, User, Attempt, Quiz
from datetime import datetime, timezone
from sqlalchemy import func
import pytz  # Import pytz for handling user time zones


from models import db, User, Attempt, Quiz
from datetime import datetime, timezone
from sqlalchemy import func
import pytz

def reset_credits(user):
    now_utc = datetime.now(timezone.utc)
    
    # --- THIS IS THE FIX ---
    # We make user.plan_expiration timezone-aware before comparing it to the aware now_utc
    plan_expired = (
        user.plan_expiration and 
        user.plan_expiration.replace(tzinfo=timezone.utc) < now_utc
    )

    if user.plan is None or plan_expired:
        user.plan = 'free'
        user.plan_expiration = None
        user.credits = 5
        user.static_credits = 0
        user.dynamic_credits = 0
        user.last_reset_date = now_utc
        db.session.commit()
        return # Exit after resetting to free

    # Get the user's time zone or default to UTC
    try:
        user_tz = pytz.timezone(user.timezone)
    except (pytz.UnknownTimeZoneError, TypeError):
        user_tz = pytz.UTC
    
    # Convert last_reset_date to user's local time
    last_reset_local = user.last_reset_date.replace(tzinfo=pytz.utc).astimezone(user_tz)
    now_local = now_utc.astimezone(user_tz)
    
    # Check if the month has changed in the user's local time
    if last_reset_local.month != now_local.month or last_reset_local.year != now_local.year:
        if user.plan == 'free':
            user.credits = 5
            user.static_credits = 0
            user.dynamic_credits = 0
        elif user.plan == 'pro':
            user.credits = 50
            user.static_credits = 0
            user.dynamic_credits = 0
        elif user.plan == 'premium':
            user.credits = 0
            user.static_credits = 50
            user.dynamic_credits = 20
        # Enterprise plan has unlimited credits, so no reset is needed
        
        # Update last_reset_date to now in UTC
        user.last_reset_date = now_utc
        db.session.commit()

def get_attempts_this_month(user_id, generation_type=None):
    now_utc = datetime.now(timezone.utc)
    
    # Get the user's time zone
    user = User.query.get(user_id)
    user_tz = pytz.timezone(user.timezone) if user and user.timezone else pytz.UTC
    
    # Calculate the first day of the current month in user's local time
    now_local = now_utc.astimezone(user_tz)
    first_day_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Convert first_day_local back to UTC for database query
    first_day_utc = first_day_local.astimezone(pytz.UTC)
    
    query = Attempt.query.filter(Attempt.user_id == user_id, Attempt.timestamp >= first_day_utc)
    if generation_type:
        query = query.join(Quiz).filter(Quiz.generation_type == generation_type)
    return query.count()