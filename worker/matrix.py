import random


def random_matrix(n):
    return [[random.randint(0, 9) for _ in range(n)] for _ in range(n)]


def multiply(a, b, on_progress):
    n = len(a)
    c = []
    for i in range(n):
        row = []
        for j in range(n):
            s = 0
            for k in range(n):
                s += a[i][k] * b[k][j]
            row.append(s)
        c.append(row)
        on_progress(i + 1, n)
    return c