import os
import psycopg2


def connect():
    return psycopg2.connect(
        host=os.environ.get('DB_HOST', 'db'),
        port=int(os.environ.get('DB_PORT', 5432)),
        dbname=os.environ.get('DB_NAME', 'matrixdb'),
        user=os.environ.get('DB_USER', 'matrix'),
        password=os.environ.get('DB_PASSWORD', 'matrix'),
    )