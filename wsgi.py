"""WSGI 入口。

本地开发：python wsgi.py
服务器：gunicorn -w 2 -b 0.0.0.0:5000 wsgi:app
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
