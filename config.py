import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'your_secret_key_here')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'postgresql://postgres.pyzvcehhqaywbrtyeckw:QuizCraft1000@aws-0-ap-south-1.pooler.supabase.com:6543/postgres')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', 'include1iostream2@gmail.com')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', 'yscf enwg ovor sste')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'include1iostream2@gmail.com')

    # --- NEW: Google OAuth Credentials ---
    # Replace with your actual credentials from the Google Cloud Console
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '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')
