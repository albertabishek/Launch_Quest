from flask_mail import Mail
from flask_socketio import SocketIO

mail = Mail()
socketio = SocketIO()

# --- State for tracking online users ---
# This shared dictionary will hold the state of online users for each chat room.
# Moving it here from app.py resolves the circular import.
# Format: { 'quiz_id_room': {session_id: {'id': user_id, 'username': username}}, ... }
online_users = {}