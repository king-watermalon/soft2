"""扩展版 WSGI 入口 v2（新增文件，``wsgi.py`` 一行未改）。

用法
----
开发：``python app_v2.py``
部署：``gunicorn -w 1 --threads 4 app_v2:app``

两个入口并存的意义
------------------
``wsgi:app`` 是初始版本的应用，用于"变更前行为"的对照与原有回归测试；
``app_v2:app`` 在它之上装配了 CR-01 / CR-02 扩展。同一份 ``app/`` 代码、
同一套数据库结构（扩展只加列加表），可以随时切换，回到变更前不需要
回滚代码。
"""

from __future__ import annotations

from ext_v2.factory_v2 import create_ext_app

app = create_ext_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
