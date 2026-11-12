import os
from flask import Flask

app = Flask(__name__)
port = int(os.environ.get('PORT', 3001))


@app.route('/')
def index():
    return 'Відповів сервер на порту ' + str(port)


@app.route('/hello')
def hello():
    return 'Привіт!'

if __name__ == '__main__':
    app.run(port=port)

