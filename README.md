# Множення матриць

Сайт, де можна запустити множення двох випадкових матриць n×n.
Запити розподіляє nginx між двома серверами Flask, а саме множення роблять воркери,
які беруть задачі з черги в PostgreSQL. Воркер можна запустити і на іншому комп'ютері.

## Як запустити

Потрібен Docker. Спочатку треба створити сертифікат для HTTPS:

    mkdir -p nginx/certs
    openssl req -x509 -newkey rsa:2048 -nodes -days 365 -keyout nginx/certs/key.pem -out nginx/certs/cert.pem -subj "/CN=localhost"

Потім:

    docker compose up -d --build

Сайт: https://localhost:8443 (браузер попередить про сертифікат, це нормально).
Адмін: admin / admin.

## Обмеження

Розмір матриці від 2 до 600, одна задача рахується не довше 300 с.
У користувача може бути до 3 активних задач, у черзі загалом до 20.
Постійно працюють 2 воркери, автоскейлер додає ще до 2, коли всі зайняті,
і прибирає їх після 30 с простою. Воркер, який мовчить 20 с, вважається мертвим,
і його задача повертається в чергу.

Усе це змінюється через змінні середовища в docker-compose.yml
(MAX_N, MAX_ACTIVE, MAX_QUEUE, TIME_LIMIT, MAX_AUTO, IDLE_SECONDS, DEAD_SECONDS).

## Воркер з іншого комп'ютера

    cd worker
    pip install psycopg2-binary
    DB_HOST=<IP комп'ютера з базою> DB_PORT=5433 WORKER_NAME=worker-remote python worker.py
