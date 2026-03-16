import os
from datetime import datetime
from functools import wraps
from io import BytesIO

import fitz  # PyMuPDF
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from sqlalchemy import text
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from models import Book, BookPage, LoginAttempt, ReadingProgress, User, Vocabulary, db

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-key-12345'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_UPLOAD_MB', '64')) * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped_view


def generate_placeholder_email(username):
    normalized = secure_filename((username or '').strip().lower()).replace('-', '_') or 'user'
    return f'{normalized}@inklingo.local'


def unique_email_for_username(username, requested_email=''):
    base_email = (requested_email or '').strip() or generate_placeholder_email(username)
    candidate = base_email
    counter = 1
    while User.query.filter_by(email=candidate).first():
        local_part, _, domain = generate_placeholder_email(username).partition('@')
        candidate = f'{local_part}{counter}@{domain}'
        counter += 1
    return candidate


def get_client_ip():
    forwarded_for = request.headers.get('X-Forwarded-For', '')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.remote_addr or 'desconhecido'


def log_login_attempt(username, success, user=None, failure_reason=None):
    attempt = LoginAttempt(
        username_attempted=(username or '').strip(),
        success=success,
        ip_address=get_client_ip(),
        user_agent=(request.user_agent.string or '')[:255],
        failure_reason=failure_reason,
        user_id=user.id if user else None,
    )
    db.session.add(attempt)
    db.session.commit()


def ensure_database_schema():
    db.create_all()

    user_columns = {
        row[1]
        for row in db.session.execute(text("PRAGMA table_info('user')")).fetchall()
    }
    if 'is_admin' not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT 0"))
    if 'created_at' not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN created_at DATETIME"))
        db.session.execute(text("UPDATE user SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))

    login_attempt_table_exists = db.session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='login_attempt'")
    ).fetchone()
    if not login_attempt_table_exists:
        LoginAttempt.__table__.create(db.engine)

    db.session.commit()


def ensure_admin_account():
    admin_user = User.query.filter_by(username='admin').first()
    if admin_user:
        if not admin_user.is_admin:
            admin_user.is_admin = True
            if not admin_user.email:
                admin_user.email = 'admin@inklingo.local'
            db.session.commit()
        return

    if User.query.filter_by(is_admin=True).first():
        return

    default_password = os.getenv('ADMIN_PASSWORD', 'admin123')
    admin_user = User(
        username='admin',
        email='admin@inklingo.local',
        password_hash=generate_password_hash(default_password),
        is_admin=True,
    )
    db.session.add(admin_user)
    db.session.commit()


def is_last_admin(user):
    return user.is_admin and User.query.filter_by(is_admin=True).count() == 1


def get_book_pdf_path(book):
    return os.path.join(app.config['UPLOAD_FOLDER'], book.filename)


def normalize_word_token(raw_word):
    return raw_word.strip().strip('.,!?;:()[]{}"\'“”‘’')


def extract_pdf_page_data(book, page_number):
    file_path = get_book_pdf_path(book)
    if not os.path.exists(file_path):
        raise FileNotFoundError('Arquivo PDF não encontrado.')

    doc = fitz.open(file_path)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise IndexError('Página inválida.')

        page = doc.load_page(page_number - 1)
        page_rect = page.rect
        words = []

        for x0, y0, x1, y1, word_text, *_rest in page.get_text('words'):
            clean_word = normalize_word_token(word_text)
            if not clean_word:
                continue
            words.append({
                'text': word_text,
                'clean': clean_word,
                'left_pct': round((x0 / page_rect.width) * 100, 4),
                'top_pct': round((y0 / page_rect.height) * 100, 4),
                'width_pct': round(((x1 - x0) / page_rect.width) * 100, 4),
                'height_pct': round(((y1 - y0) / page_rect.height) * 100, 4),
            })

        return {
            'width': page_rect.width,
            'height': page_rect.height,
            'words': words,
            'total_pages': doc.page_count,
        }
    finally:
        doc.close()


def render_pdf_page_image(book, page_number, zoom=1.8):
    file_path = get_book_pdf_path(book)
    if not os.path.exists(file_path):
        raise FileNotFoundError('Arquivo PDF não encontrado.')

    doc = fitz.open(file_path)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise IndexError('Página inválida.')

        page = doc.load_page(page_number - 1)
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        return BytesIO(pixmap.tobytes('png'))
    finally:
        doc.close()


@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(_error):
    max_upload_mb = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
    flash(f'O arquivo excede o limite de {max_upload_mb}MB.', 'danger')
    return redirect(url_for('dashboard'))


@app.errorhandler(403)
def handle_forbidden(_error):
    flash('Você não tem permissão para acessar essa área.', 'danger')
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            log_login_attempt(username, True, user=user)
            return redirect(url_for('dashboard'))

        log_login_attempt(username, False, failure_reason='Credenciais inválidas')
        flash('Login ou senha inválidos', 'danger')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password') or ''

        if not username or not password:
            flash('Informe login e senha.', 'danger')
        elif User.query.filter_by(username=username).first():
            flash('Esse login já está em uso.', 'danger')
        else:
            user = User(
                username=username,
                email=unique_email_for_username(username, email),
                password_hash=generate_password_hash(password),
                is_admin=User.query.count() == 0,
            )
            db.session.add(user)
            db.session.commit()
            if user.is_admin:
                flash('Conta criada com sucesso! Essa conta recebeu acesso de admin.', 'success')
            else:
                flash('Conta criada com sucesso!', 'success')
            return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    books = Book.query.filter_by(user_id=current_user.id).all()
    vocab_count = Vocabulary.query.filter_by(user_id=current_user.id).count()
    daily_words = Vocabulary.query.filter_by(user_id=current_user.id).order_by(Vocabulary.date_saved.desc()).limit(10).all()

    last_progress = ReadingProgress.query.filter_by(user_id=current_user.id).order_by(ReadingProgress.last_read.desc()).first()
    last_book = None
    if last_progress:
        last_book = Book.query.get(last_progress.book_id)

    return render_template(
        'dashboard.html',
        books=books,
        vocab_count=vocab_count,
        daily_words=daily_words,
        last_book=last_book,
        last_progress=last_progress,
    )


@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    users = User.query.order_by(User.created_at.desc(), User.username.asc()).all()
    login_attempts = LoginAttempt.query.order_by(LoginAttempt.attempted_at.desc()).limit(150).all()
    stats = {
        'total_users': User.query.count(),
        'admins': User.query.filter_by(is_admin=True).count(),
        'books': Book.query.count(),
        'failed_logins': LoginAttempt.query.filter_by(success=False).count(),
    }
    return render_template('admin_dashboard.html', users=users, login_attempts=login_attempts, stats=stats)


@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_user(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password') or ''
        make_admin = request.form.get('is_admin') == 'on'

        if not username:
            flash('O login do usuário é obrigatório.', 'danger')
        elif User.query.filter(User.username == username, User.id != user.id).first():
            flash('Esse login já está em uso por outro usuário.', 'danger')
        elif email and User.query.filter(User.email == email, User.id != user.id).first():
            flash('Esse e-mail já está em uso por outro usuário.', 'danger')
        elif is_last_admin(user) and not make_admin:
            flash('Não é possível remover o status do último administrador.', 'danger')
        else:
            user.username = username
            user.email = email or user.email or unique_email_for_username(username)
            user.is_admin = make_admin
            if password:
                user.password_hash = generate_password_hash(password)
            db.session.commit()
            flash('Usuário atualizado com sucesso.', 'success')
            return redirect(url_for('admin_dashboard'))

    return render_template('admin_user_edit.html', managed_user=user)


@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash('Você não pode excluir a própria conta logada.', 'danger')
        return redirect(url_for('admin_dashboard'))
    if is_last_admin(user):
        flash('Não é possível excluir o último administrador.', 'danger')
        return redirect(url_for('admin_dashboard'))

    db.session.delete(user)
    db.session.commit()
    flash('Usuário excluído com sucesso.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/upload', methods=['POST'])
@login_required
def upload_book():
    if 'file' not in request.files:
        flash('Nenhum arquivo enviado', 'danger')
        return redirect(url_for('dashboard'))

    file = request.files['file']
    if file.filename == '':
        flash('Nenhum arquivo selecionado', 'danger')
        return redirect(url_for('dashboard'))

    if file and file.filename.lower().endswith('.pdf'):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        try:
            doc = fitz.open(file_path)
            new_book = Book(title=filename, filename=filename, user_id=current_user.id)
            db.session.add(new_book)
            db.session.flush()

            for i in range(len(doc)):
                page = doc.load_page(i)
                text_content = page.get_text()
                new_page = BookPage(page_number=i + 1, content=text_content, book_id=new_book.id)
                db.session.add(new_page)

            db.session.commit()
            flash('Livro enviado e processado com sucesso!', 'success')
        except Exception as exc:
            db.session.rollback()
            if os.path.exists(file_path):
                os.remove(file_path)
            flash(f'Erro ao processar PDF: {str(exc)}', 'danger')
    else:
        flash('Apenas arquivos PDF são permitidos', 'danger')

    return redirect(url_for('dashboard'))


@app.route('/reader/<int:book_id>')
@login_required
def reader(book_id):
    book = Book.query.get_or_404(book_id)
    if book.user_id != current_user.id:
        flash('Acesso negado', 'danger')
        return redirect(url_for('dashboard'))

    progress = ReadingProgress.query.filter_by(user_id=current_user.id, book_id=book_id).first()
    if not progress:
        progress = ReadingProgress(user_id=current_user.id, book_id=book_id, last_page=1)
        db.session.add(progress)
        db.session.commit()

    page_num = request.args.get('page', progress.last_page, type=int)
    try:
        page_data = extract_pdf_page_data(book, page_num)
    except FileNotFoundError:
        flash('Arquivo original do livro não foi encontrado.', 'danger')
        return redirect(url_for('dashboard'))
    except IndexError:
        flash('Página inválida.', 'danger')
        return redirect(url_for('reader', book_id=book.id, page=progress.last_page))

    progress.last_page = page_num
    db.session.commit()

    saved_words = Vocabulary.query.filter_by(user_id=current_user.id).order_by(Vocabulary.date_saved.desc()).limit(20).all()

    return render_template(
        'reader.html',
        book=book,
        page_num=page_num,
        total_pages=page_data['total_pages'],
        page_image_width=page_data['width'],
        page_image_height=page_data['height'],
        page_words=page_data['words'],
        saved_words=saved_words,
    )


@app.route('/reader/<int:book_id>/page-image/<int:page_num>')
@login_required
def reader_page_image(book_id, page_num):
    book = Book.query.get_or_404(book_id)
    if book.user_id != current_user.id:
        return '', 403

    try:
        image_stream = render_pdf_page_image(book, page_num)
    except (FileNotFoundError, IndexError):
        return '', 404

    return send_file(image_stream, mimetype='image/png')


@app.route('/api/save_word', methods=['POST'])
@login_required
def save_word():
    data = request.json or {}
    word = data.get('word')
    translation = data.get('translation')

    if not word:
        return jsonify({'success': False, 'message': 'Palavra não fornecida'}), 400

    today = datetime.utcnow().date()
    count_today = Vocabulary.query.filter(
        Vocabulary.user_id == current_user.id,
        db.func.date(Vocabulary.date_saved) == today,
    ).count()

    if count_today >= 10:
        return jsonify({'success': False, 'message': 'Limite diário de 10 palavras atingido!'}), 400

    existing = Vocabulary.query.filter_by(user_id=current_user.id, word=word).first()
    if existing:
        return jsonify({'success': False, 'message': 'Palavra já salva!'}), 400

    new_vocab = Vocabulary(word=word, translation=translation, user_id=current_user.id)
    db.session.add(new_vocab)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Palavra salva!'})


@app.route('/api/delete_word', methods=['POST'])
@login_required
def delete_word():
    data = request.json or {}
    word = (data.get('word') or '').strip()

    if not word:
        return jsonify({'success': False, 'message': 'Palavra não fornecida'}), 400

    vocab = Vocabulary.query.filter_by(user_id=current_user.id, word=word).first()
    if not vocab:
        return jsonify({'success': False, 'message': 'Palavra não encontrada'}), 404

    db.session.delete(vocab)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Palavra removida!'})


@app.route('/api/translate', methods=['POST'])
@login_required
def translate():
    data = request.json or {}
    word = data.get('word')
    return jsonify({'word': word, 'translation': 'Tradução pendente...'})


with app.app_context():
    ensure_database_schema()
    ensure_admin_account()


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
