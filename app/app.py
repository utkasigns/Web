import json
import os
import random
from datetime import datetime, timedelta, timezone

import jwt
from flask import Flask, flash, redirect, render_template, request
from werkzeug.security import check_password_hash, generate_password_hash

from db import run

APP_NAME = os.environ.get('APP_NAME', 'app-local')
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret')
MAX_N = int(os.environ.get('MAX_N', 600))
MAX_ACTIVE = int(os.environ.get('MAX_ACTIVE', 3))
MAX_QUEUE = int(os.environ.get('MAX_QUEUE', 20))
MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 4))
DEFAULT_K = 1.7e-7

STATUSES = {
    'queued': ('У черзі', 'secondary'),
    'running': ('Виконується', 'primary'),
    'done': ('Готово', 'success'),
    'cancelled': ('Скасовано', 'warning'),
    'timeout': ('Перевищено час', 'danger'),
    'failed': ('Помилка', 'danger'),
}

app = Flask(__name__)
app.secret_key = SECRET_KEY


def random_matrix(n):
    return [[random.randint(0, 9) for _ in range(n)] for _ in range(n)]


def current_user():
    token = request.cookies.get('token')
    if not token:
        return None
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
    except jwt.InvalidTokenError:
        return None
    return run('SELECT id, username, is_admin FROM users WHERE id = %s', (data['user_id'],), 'one')


def login_response(user_id):
    payload = {'user_id': user_id, 'exp': datetime.now(timezone.utc) + timedelta(hours=8)}
    token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')
    response = redirect('/')
    response.set_cookie('token', token, httponly=True, samesite='Lax')
    return response


def alive_workers():
    row = run("SELECT count(*) AS c FROM workers WHERE last_heartbeat > now() - interval '15 seconds'", fetch='one')
    return row['c']


def seconds_per_op():
    row = run(
        "SELECT sum(extract(epoch FROM finished_at - started_at)) / sum(n * n * n) AS k FROM ("
        "SELECT n, started_at, finished_at FROM tasks WHERE status = 'done' "
        "ORDER BY finished_at DESC LIMIT 20) recent",
        fetch='one',
    )
    return float(row['k']) if row['k'] else DEFAULT_K


def queue_waits():
    k = seconds_per_op()
    workers = max(alive_workers(), 1)
    running = run("SELECT n, progress FROM tasks WHERE status = 'running'", fetch='all')
    total = sum(k * t['n'] ** 3 * (100 - t['progress']) / 100 for t in running)
    queued = run("SELECT id, n FROM tasks WHERE status = 'queued' ORDER BY created_at", fetch='all')
    waits = {}
    for position, t in enumerate(queued, start=1):
        waits[t['id']] = (position, round(total / workers))
        total += k * t['n'] ** 3
    return waits


@app.after_request
def served_by(response):
    response.headers['X-Served-By'] = APP_NAME
    return response


@app.context_processor
def common():
    return {'server_name': APP_NAME, 'user': current_user()}


def user_tasks(user):
    tasks = run(
        'SELECT id, n, status, progress, worker, result, error FROM tasks '
        'WHERE user_id = %s ORDER BY id DESC LIMIT 30',
        (user['id'],), 'all',
    )
    waits = queue_waits()
    for t in tasks:
        t['result'] = json.loads(t['result']) if t['result'] else None
        t['wait'] = waits.get(t['id'])
    return tasks


@app.route('/')
def index():
    user = current_user()
    if not user:
        return redirect('/login')
    return render_template(
        'index.html', tasks=user_tasks(user),
        max_n=MAX_N, max_active=MAX_ACTIVE, statuses=STATUSES,
    )


@app.route('/tasks/table')
def tasks_table():
    user = current_user()
    if not user:
        return '', 401
    return render_template('_tasks.html', tasks=user_tasks(user), statuses=STATUSES)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = run('SELECT id, password_hash FROM users WHERE username = %s', (username,), 'one')
        if user and check_password_hash(user['password_hash'], password):
            return login_response(user['id'])
        flash('Неправильний логін або пароль', 'danger')
    return render_template('login.html')


@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    if len(username) < 3 or len(password) < 4:
        flash('Логін мінімум 3 символи, пароль мінімум 4', 'danger')
        return redirect('/login')
    row = run(
        'INSERT INTO users (username, password_hash) VALUES (%s, %s) '
        'ON CONFLICT (username) DO NOTHING RETURNING id',
        (username, generate_password_hash(password)), 'one',
    )
    if not row:
        flash('Такий логін уже зайнятий', 'danger')
        return redirect('/login')
    return login_response(row['id'])


@app.route('/logout')
def logout():
    response = redirect('/login')
    response.delete_cookie('token')
    return response


@app.route('/tasks', methods=['POST'])
def create_task():
    user = current_user()
    if not user:
        return redirect('/login')
    try:
        n = int(request.form.get('n', ''))
    except ValueError:
        n = 0
    if n < 2 or n > MAX_N:
        flash(f'Розмір матриці має бути від 2 до {MAX_N}', 'danger')
        return redirect('/')
    active = run(
        "SELECT count(*) AS c FROM tasks WHERE user_id = %s AND status IN ('queued', 'running')",
        (user['id'],), 'one',
    )['c']
    if active >= MAX_ACTIVE:
        flash(f'Не більше {MAX_ACTIVE} активних задач одночасно', 'danger')
        return redirect('/')
    queued = run("SELECT count(*) AS c FROM tasks WHERE status = 'queued'", fetch='one')['c']
    if queued >= MAX_QUEUE:
        flash('Система перевантажена, спробуйте пізніше', 'danger')
        return redirect('/')
    row = run(
        'INSERT INTO tasks (user_id, n, matrix_a, matrix_b) VALUES (%s, %s, %s, %s) RETURNING id',
        (user['id'], n, json.dumps(random_matrix(n)), json.dumps(random_matrix(n))), 'one',
    )
    free = run(
        "SELECT count(*) AS c FROM workers WHERE status = 'idle' "
        "AND last_heartbeat > now() - interval '15 seconds'",
        fetch='one',
    )['c']
    if free == 0:
        position, wait = queue_waits().get(row['id'], (1, 0))
        flash(
            f'Усі воркери зайняті: задачу №{row["id"]} поставлено в чергу '
            f'(місце {position}, очікування ~{wait} с)',
            'warning',
        )
    else:
        flash(f'Задачу №{row["id"]} створено', 'success')
    return redirect('/')


@app.route('/tasks/<int:task_id>/cancel', methods=['POST'])
def cancel_task(task_id):
    user = current_user()
    if not user:
        return redirect('/login')
    run(
        "UPDATE tasks SET status = 'cancelled', finished_at = now() "
        "WHERE id = %s AND user_id = %s AND status = 'queued'",
        (task_id, user['id']),
    )
    run(
        "UPDATE tasks SET cancel_requested = TRUE "
        "WHERE id = %s AND user_id = %s AND status = 'running'",
        (task_id, user['id']),
    )
    flash(f'Задачу №{task_id} скасовано', 'warning')
    return redirect('/')


@app.route('/admin')
def admin():
    user = current_user()
    if not user:
        return redirect('/login')
    if not user['is_admin']:
        return 'Доступ лише для адміністратора', 403
    workers = run(
        "SELECT name, status, task_id, tasks_done, "
        "round(extract(epoch FROM now() - last_heartbeat)) AS ago, "
        "last_heartbeat > now() - interval '15 seconds' AS alive "
        "FROM workers ORDER BY name",
        fetch='all',
    )
    tasks = run(
        "SELECT t.id, u.username, t.n, t.status, t.progress, t.worker "
        "FROM tasks t JOIN users u ON u.id = t.user_id "
        "WHERE t.status IN ('queued', 'running') ORDER BY t.id",
        fetch='all',
    )
    counts = {r['status']: r['c'] for r in run('SELECT status, count(*) AS c FROM tasks GROUP BY status', fetch='all')}
    alive = sum(1 for w in workers if w['alive'])
    return render_template(
        'admin.html', workers=workers, tasks=tasks, counts=counts,
        alive=alive, max_workers=MAX_WORKERS, statuses=STATUSES,
    )


def ensure_admin():
    run(
        'INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, TRUE) '
        'ON CONFLICT (username) DO NOTHING',
        (os.environ.get('ADMIN_USER', 'admin'), generate_password_hash(os.environ.get('ADMIN_PASSWORD', 'admin'))),
    )


if __name__ == '__main__':
    ensure_admin()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))