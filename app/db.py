import os

import psycopg2
from psycopg2.extras import RealDictCursor


def connect():
    return psycopg2.connect(
        host=os.environ.get('DB_HOST', 'db'),
        port=int(os.environ.get('DB_PORT', 5432)),
        dbname=os.environ.get('DB_NAME', 'matrixdb'),
        user=os.environ.get('DB_USER', 'matrix'),
        password=os.environ.get('DB_PASSWORD', 'matrix'),
        cursor_factory=RealDictCursor,
    )


def run(sql, params=(), fetch=None):
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        result = None
        if fetch == 'one':
            result = cur.fetchone()
        elif fetch == 'all':
            result = cur.fetchall()
        conn.commit()
        return result
    finally:
        conn.close()