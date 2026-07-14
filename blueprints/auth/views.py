from flask import Blueprint, flash, redirect, render_template, request, session, url_for, abort
from werkzeug.security import check_password_hash, generate_password_hash

from models import User, db  

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Comprobamos si el sistema carece de usuarios administradores
    any_user_exists = User.query.first() is not None

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('Sesión iniciada correctamente.', 'success')
            return redirect(url_for('invoices.facturas'))

        flash('Usuario o contraseña incorrectos.', 'danger')

    return render_template('login.html', any_user_exists=any_user_exists)


@auth_bp.route('/setup_admin', methods=['POST'])
def setup_admin():
    # Bloqueo total: Si ya existe un usuario en la DB, abortamos con un 403 (Prohibido)
    if User.query.first() is not None:
        abort(403)

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()

    if not username or not password:
        flash('Por favor, rellena todos los campos.', 'danger')
        return redirect(url_for('auth.login'))
    
    if len(password) < 6:
        flash('La contraseña debe tener al menos 6 caracteres.', 'danger')
        return redirect(url_for('auth.login'))

    try:
        hashed_password = generate_password_hash(password)
        new_admin = User(username=username, password=hashed_password)
        
        db.session.add(new_admin)
        db.session.commit()
        
        flash('Administrador principal configurado con éxito. Ya puedes iniciar sesión.', 'success')
    except Exception:
        db.session.rollback()
        flash('Ocurrió un error al configurar el administrador. Inténtalo de nuevo.', 'danger')

    return redirect(url_for('auth.login'))


@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada', 'info')
    return redirect(url_for('auth.login'))