import os
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO

db = SQLAlchemy()
socketio = SocketIO(async_mode='threading')

# Import FaceRecognitionSystem AFTER db/socketio are defined
from attendance_logic import FaceRecognitionSystem
frs = FaceRecognitionSystem()
