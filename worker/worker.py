import json
import os
import socket
import time

from db import connect
from matrix import multiply

NAME = os.environ.get('WORKER_NAME', socket.gethostname())
TIME_LIMIT = int(os.environ.get('TIME_LIMIT', 120))


class Cancelled(Exception):
    pass


class TimeLimit(Exception):
    pass


def register(cur):
    cur.execute(
        "INSERT INTO workers (name) VALUES (%s) "
        "ON CONFLICT (name) DO UPDATE SET status = 'idle', task_id = NULL, "
        "last_heartbeat = now(), stop_requested = FALSE",
        (NAME,),
    )


def heartbeat(cur):
    cur.execute(
        "UPDATE workers SET last_heartbeat = now() WHERE name = %s RETURNING stop_requested",
        (NAME,),
    )
    return cur.fetchone()[0]


def claim(cur):
    cur.execute(
        "UPDATE tasks SET status = 'running', worker = %s, started_at = now() "
        "WHERE id = (SELECT id FROM tasks WHERE status = 'queued' "
        "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) "
        "RETURNING id, matrix_a, matrix_b",
        (NAME,),
    )
    return cur.fetchone()


def run_task(conn, cur, task_id, a, b):
    cur.execute("UPDATE workers SET status = 'busy', task_id = %s WHERE name = %s", (task_id, NAME))
    conn.commit()
    started = time.time()
    last_percent = 0

    def on_progress(done, total):
        nonlocal last_percent
        percent = done * 100 // total
        if percent == last_percent:
            return
        last_percent = percent
        cur.execute(
            "UPDATE tasks SET progress = %s WHERE id = %s RETURNING cancel_requested",
            (percent, task_id),
        )
        cancel = cur.fetchone()[0]
        cur.execute("UPDATE workers SET last_heartbeat = now() WHERE name = %s", (NAME,))
        conn.commit()
        if cancel:
            raise Cancelled()
        if time.time() - started > TIME_LIMIT:
            raise TimeLimit()

    try:
        c = multiply(a, b, on_progress)
        result = {
            'sum': sum(sum(row) for row in c),
            'corner': [row[:3] for row in c[:3]],
            'seconds': round(time.time() - started, 2),
        }
        cur.execute(
            "UPDATE tasks SET status = 'done', progress = 100, result = %s, finished_at = now() WHERE id = %s",
            (json.dumps(result), task_id),
        )
        cur.execute("UPDATE workers SET tasks_done = tasks_done + 1 WHERE name = %s", (NAME,))
    except Cancelled:
        cur.execute("UPDATE tasks SET status = 'cancelled', finished_at = now() WHERE id = %s", (task_id,))
    except TimeLimit:
        cur.execute(
            "UPDATE tasks SET status = 'timeout', error = %s, finished_at = now() WHERE id = %s",
            (f'Перевищено ліміт часу {TIME_LIMIT} с', task_id),
        )
    except Exception as e:
        conn.rollback()
        cur.execute(
            "UPDATE tasks SET status = 'failed', error = %s, finished_at = now() WHERE id = %s",
            (str(e), task_id),
        )
    cur.execute("UPDATE workers SET status = 'idle', task_id = NULL WHERE name = %s", (NAME,))
    conn.commit()


def main():
    conn = connect()
    cur = conn.cursor()
    register(cur)
    conn.commit()
    print('Воркер', NAME, 'запущено')
    while True:
        if heartbeat(cur):
            break
        task = claim(cur)
        conn.commit()
        if task is None:
            time.sleep(1)
            continue
        task_id, a_json, b_json = task
        print('Взяв задачу', task_id)
        run_task(conn, cur, task_id, json.loads(a_json), json.loads(b_json))
        print('Завершив задачу', task_id)
    cur.execute('DELETE FROM workers WHERE name = %s', (NAME,))
    conn.commit()
    conn.close()


if __name__ == '__main__':
    main()