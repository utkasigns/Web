import os
from flask import Flask

app = Flask(__name__)
port = int(os.environ.get('PORT', 3001))


@app.route('/')
def index():
    return 'Відповів сервер на порту ' + str(port)


if __name__ == '__main__':
    app.run(port=port)

