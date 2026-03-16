from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    books = db.relationship('Book', backref='owner', lazy=True, cascade="all, delete-orphan")
    vocabularies = db.relationship('Vocabulary', backref='user', lazy=True, cascade="all, delete-orphan")
    progress = db.relationship('ReadingProgress', backref='user', lazy=True, cascade="all, delete-orphan")
    login_attempts = db.relationship('LoginAttempt', backref='user', lazy=True, cascade="all, delete-orphan")

class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    pages = db.relationship('BookPage', backref='book', lazy=True, cascade="all, delete-orphan")

class BookPage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    page_number = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)

class Vocabulary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    word = db.Column(db.String(100), nullable=False)
    translation = db.Column(db.String(200))
    date_saved = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='learning') # learning, mastered
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class ReadingProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    last_page = db.Column(db.Integer, default=1)
    last_read = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('book.id'), nullable=False)


class LoginAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username_attempted = db.Column(db.String(80), nullable=False)
    success = db.Column(db.Boolean, default=False, nullable=False)
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(255))
    failure_reason = db.Column(db.String(255))
    attempted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
