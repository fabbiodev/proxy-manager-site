import os
import logging
import sqlite3
import random
from collections import defaultdict
from datetime import datetime, timedelta

from flask import (
    Flask, render_template, request,
    redirect, session, url_for, flash
)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'lol'

DB_USERS    = 'users.db'
DB_PROXIES  = 'proxies.db'
DB_DELETED  = 'deleted_proxies.db'
LOG_DIR     = 'logs'
LOG_FILE    = os.path.join(LOG_DIR, 'actions.log')

# ——————————————————————————————————————————————————————————————————————
#                ЛОГИРОВАНИЕ
# ——————————————————————————————————————————————————————————————————————
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def log_action(user, ip, action, details=''):
    logging.info(f"user={user} ip={ip} action={action} {details}")
# ——————————————————————————————————————————————————————————————————————

# Защита от перебора
failed_attempts = defaultdict(list)
banned_ips      = {}
MAX_ATTEMPTS    = 3
WINDOW          = timedelta(minutes=1)
BAN_DURATION    = timedelta(minutes=5)

def get_db(path):
    return sqlite3.connect(path)

def init_dbs():
    # users.db
    u = get_db(DB_USERS)
    u.execute('''
      CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
      )
    ''')
    u.execute('INSERT OR IGNORE INTO users(username,password) VALUES(?,?)', ('user','samokat'))
    u.execute('INSERT OR IGNORE INTO users(username,password) VALUES(?,?)', ('admin','bebra'))
    u.commit(); u.close()

    # proxies.db
    p = get_db(DB_PROXIES)
    p.execute('PRAGMA journal_mode=WAL')
    p.execute('PRAGMA synchronous=FULL')
    p.execute('PRAGMA foreign_keys=ON')
    p.execute('''
      CREATE TABLE IF NOT EXISTS proxies (
        id INTEGER PRIMARY KEY,
        ip TEXT NOT NULL,
        port INTEGER NOT NULL CHECK(port>0 AND port<65536),
        login TEXT NOT NULL,
        password TEXT NOT NULL,
        UNIQUE(ip,port)
      )
    ''')
    p.commit(); p.close()

    # deleted_proxies.db
    d = get_db(DB_DELETED)
    d.execute('''
      CREATE TABLE IF NOT EXISTS deleted_proxies (
        id INTEGER PRIMARY KEY,
        ip TEXT NOT NULL,
        port INTEGER NOT NULL,
        login TEXT NOT NULL,
        password TEXT NOT NULL,
        deleted_at TEXT NOT NULL
      )
    ''')
    d.commit(); d.close()

init_dbs()


@app.route('/', methods=['GET','POST'])
def login():
    ip_addr = request.remote_addr
    now = datetime.now()
    ban = banned_ips.get(ip_addr)
    if ban and now < ban:
        mins = int((ban-now).total_seconds()//60)+1
        return render_template('index.html',
                               error=f"Слишком много попыток. Попробуйте через {mins} мин.")
    error = None
    if request.method=='POST':
        user = request.form['username']
        pw   = request.form['password']
        atts = [t for t in failed_attempts[ip_addr] if now-t <= WINDOW]
        failed_attempts[ip_addr] = atts

        db = get_db(DB_USERS)
        ok = db.execute(
            'SELECT 1 FROM users WHERE username=? AND password=?',
            (user,pw)
        ).fetchone()
        db.close()

        if ok:
            session['user'] = user
            failed_attempts.pop(ip_addr, None)
            log_action(user, ip_addr, 'login', 'success')
            if user=='admin':
                return redirect(url_for('proxy', page=1))
            else:
                return redirect(url_for('get_proxy'))
        else:
            atts.append(now)
            failed_attempts[ip_addr] = atts
            if len(atts) > MAX_ATTEMPTS:
                banned_ips[ip_addr] = now + BAN_DURATION
                error = 'IP заблокирован на 5 минут'
            else:
                error = 'Неверный логин или пароль'
            log_action(user or '<unknown>', ip_addr, 'login', 'failure')
    return render_template('index.html', error=error)


@app.route('/logout')
def logout():
    user = session.get('user','<unknown>')
    ip_addr = request.remote_addr
    session.pop('user', None)
    log_action(user, ip_addr, 'logout')
    return redirect(url_for('login'))


@app.route('/upload', methods=['GET','POST'])
def upload():
    if session.get('user') != 'admin':
        return redirect(url_for('login'))

    if request.method=='POST':
        ip_addr = request.remote_addr
        debug_lines = []
        text = request.form.get('text','')
        file = request.files.get('file')
        data = ''

        if file and file.filename.lower().endswith('.txt'):
            data = file.read().decode('utf-8')
        elif text.strip():
            data = text
        else:
            flash('Нечего загружать','error')

        if data:
            lines = [L.strip() for L in data.splitlines() if L.strip()]
            db_p = get_db(DB_PROXIES)
            db_d = get_db(DB_DELETED)

            for L in lines:
                parts = L.split(':')
                if len(parts) != 4:
                    debug_lines.append(f"[ошибка] Неверный формат: {L}")
                    continue
                ip, port_str, login, passwd = parts
                try:
                    port = int(port_str)
                except ValueError:
                    debug_lines.append(f"[ошибка] Некорректный порт: {L}")
                    continue

                # пропустить, если уже удалён
                if db_d.execute(
                    'SELECT 1 FROM deleted_proxies WHERE ip=? AND port=?',
                    (ip, port)
                ).fetchone():
                    debug_lines.append(f"[пропущено] Удалён ранее: {L}")
                    continue

                existing = db_p.execute(
                    'SELECT login,password FROM proxies WHERE ip=? AND port=?',
                    (ip, port)
                ).fetchone()

                if existing:
                    if (existing[0], existing[1]) == (login, passwd):
                        debug_lines.append(f"[существует] {L}")
                    else:
                        db_p.execute(
                            'UPDATE proxies SET login=?,password=? WHERE ip=? AND port=?',
                            (login, passwd, ip, port)
                        )
                        debug_lines.append(f"[обновлено] {L}")
                        log_action('admin', ip_addr, 'update_proxy',
                                   f"{ip}:{port}:{login}:{passwd}")
                else:
                    db_p.execute(
                        'INSERT INTO proxies(ip,port,login,password) VALUES(?,?,?,?)',
                        (ip, port, login, passwd)
                    )
                    debug_lines.append(f"[добавлено] {L}")
                    log_action('admin', ip_addr, 'add_proxy',
                               f"{ip}:{port}:{login}:{passwd}")

            db_p.commit()
            db_p.close()
            db_d.close()

        session['upload_debug'] = "\n".join(debug_lines)
        return redirect(url_for('upload'))

    debug = session.pop('upload_debug', None)
    return render_template('upload.html', debug=debug)


@app.route('/proxy')
def proxy():
    if session.get('user') != 'admin':
        return redirect(url_for('login'))

    page = max(int(request.args.get('page',1)),1)
    per  = 50
    offs = (page-1)*per

    db = get_db(DB_PROXIES)
    total = db.execute('SELECT COUNT(*) FROM proxies').fetchone()[0]
    rows  = db.execute(
      'SELECT id, ip, port, login, password FROM proxies '
      'ORDER BY id LIMIT ? OFFSET ?', (per, offs)
    ).fetchall()
    db.close()
    more = (offs+per) < total

    return render_template('proxy.html',
                           rows=rows, page=page, more=more, total=total)


@app.route('/get-proxy', methods=['GET','POST'])
def get_proxy():
    if 'user' not in session:
        return redirect(url_for('login'))

    ip_addr = request.remote_addr
    user    = session['user']

    if request.method=='POST':
        db = get_db(DB_PROXIES)
        rows = db.execute('SELECT id, ip, port, login, password FROM proxies').fetchall()
        if not rows:
            session['last_message'] = "В базе нет прокси."
            session.pop('last_proxy', None)
        else:
            pid, ip, port, login, password = random.choice(rows)
            proxy_str = f"{ip}:{port}:{login}:{password}"

            # удаляем из active
            db.execute('DELETE FROM proxies WHERE id=?', (pid,))
            db.commit()
            db.close()

            # сохраняем в deleted
            d = get_db(DB_DELETED)
            d.execute(
              'INSERT INTO deleted_proxies(ip,port,login,password,deleted_at) VALUES(?,?,?,?,?)',
              (ip, port, login, password, datetime.now().isoformat())
            )
            d.commit()
            d.close()

            session['last_proxy']  = proxy_str
            session.pop('last_message', None)
            log_action(user, ip_addr, 'get_proxy', proxy_str)

        return redirect(url_for('get_proxy'))

    proxy_str = session.pop('last_proxy', None)
    message   = session.pop('last_message', None)
    db        = get_db(DB_PROXIES)
    total     = db.execute('SELECT COUNT(*) FROM proxies').fetchone()[0]
    db.close()
    return render_template('user_proxy.html',
                           proxy_str=proxy_str,
                           message=message,
                           total=total)


@app.route('/delete/<int:pid>', methods=['POST'])
def delete(pid):
    if session.get('user') != 'admin':
        return redirect(url_for('login'))

    ip_addr = request.remote_addr
    user    = session['user']

    db  = get_db(DB_PROXIES)
    rec = db.execute(
        'SELECT ip,port,login,password FROM proxies WHERE id=?', (pid,)
    ).fetchone()
    if rec:
        ip,port,login,password = rec
        # логируем удаление
        log_action(user, ip_addr, 'delete_proxy', f"{ip}:{port}:{login}:{password}")

        # переносим в deleted
        d = get_db(DB_DELETED)
        d.execute(
          'INSERT INTO deleted_proxies(ip,port,login,password,deleted_at) VALUES(?,?,?,?,?)',
          (ip, port, login, password, datetime.now().isoformat())
        )
        d.commit()
        d.close()

    db.execute('DELETE FROM proxies WHERE id=?', (pid,))
    db.commit()
    db.close()

    return redirect(url_for('proxy', page=request.form.get('page',1)))


if __name__=='__main__':
    app.run(debug=True)
