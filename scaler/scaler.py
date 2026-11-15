import os
import time

import docker
import psycopg2

IMAGE = os.environ.get('WORKER_IMAGE', 'matrix-worker')
NETWORK = os.environ.get('NETWORK', 'web_default')
MAX_AUTO = int(os.environ.get('MAX_AUTO', 2))
IDLE_SECONDS = int(os.environ.get('IDLE_SECONDS', 30))
DEAD_SECONDS = int(os.environ.get('DEAD_SECONDS', 20))
LABEL = 'matrix-auto-worker'


def connect():
    conn = psycopg2.connect(
        host=os.environ.get('DB_HOST', 'db'),
        port=int(os.environ.get('DB_PORT', 5432)),
        dbname=os.environ.get('DB_NAME', 'matrixdb'),
        user=os.environ.get('DB_USER', 'matrix'),
        password=os.environ.get('DB_PASSWORD', 'matrix'),
    )
    conn.autocommit = True
    return conn


def recover_dead(cur):
    cur.execute(
        "SELECT name FROM workers WHERE last_heartbeat < now() - interval '1 second' * %s",
        (DEAD_SECONDS,),
    )
    for (name,) in cur.fetchall():
        cur.execute(
            "UPDATE tasks SET status = 'queued', progress = 0, worker = NULL, started_at = NULL "
            "WHERE status = 'running' AND worker = %s",
            (name,),
        )
        cur.execute('DELETE FROM workers WHERE name = %s', (name,))
        print('Воркер', name, 'не відповідає, його задачу повернуто в чергу')


def queue_state(cur):
    cur.execute("SELECT count(*) FROM tasks WHERE status = 'queued'")
    queued = cur.fetchone()[0]
    cur.execute(
        "SELECT count(*) FROM workers WHERE status = 'idle' "
        "AND last_heartbeat > now() - interval '1 second' * %s",
        (DEAD_SECONDS,),
    )
    idle = cur.fetchone()[0]
    return queued, idle


def scale_up(client, auto):
    names = {c.name for c in auto}
    for i in range(1, MAX_AUTO + 1):
        name = f'worker-auto-{i}'
        if name in names:
            continue
        try:
            client.containers.run(
                IMAGE, name=name, network=NETWORK, detach=True, auto_remove=True,
                labels={LABEL: '1'}, environment={'DB_HOST': 'db', 'WORKER_NAME': name},
            )
            print('Черга не порожня, запущено', name)
        except docker.errors.APIError as e:
            print('Не вдалося запустити', name, e)
        return


def scale_down(cur, auto, idle_since):
    now = time.time()
    for c in auto:
        cur.execute('SELECT status FROM workers WHERE name = %s', (c.name,))
        row = cur.fetchone()
        if row is None or row[0] != 'idle':
            idle_since.pop(c.name, None)
            continue
        first = idle_since.setdefault(c.name, now)
        if now - first > IDLE_SECONDS:
            cur.execute('UPDATE workers SET stop_requested = TRUE WHERE name = %s', (c.name,))
            idle_since.pop(c.name)
            print('Черга порожня, зупиняю', c.name)


def main():
    client = docker.from_env(version='auto')
    conn = connect()
    cur = conn.cursor()
    idle_since = {}
    print('Автоскейлер запущено')
    while True:
        recover_dead(cur)
        queued, idle = queue_state(cur)
        auto = client.containers.list(filters={'label': LABEL})
        if queued > 0:
            idle_since.clear()
            if idle == 0 and len(auto) < MAX_AUTO:
                scale_up(client, auto)
        else:
            scale_down(cur, auto, idle_since)
        time.sleep(5)


if __name__ == '__main__':
    main()