# CampusEvent 变更扩展（v2）快速上手

本目录是实验二的初始版本（`baseline-v1` → `main`）之上，按教师材料
CR-01 / CR-02 做的**增量扩展**。原有 `app/` 代码一行未改。

## 一分钟跑起来

```bash
pip install -r requirements.txt

python seed_ext_v2.py     # 原演示数据 + 年级设置 + 年级限定活动 + 邮件样例
python app_v2.py          # http://127.0.0.1:5000
```

登录 `admin / admin123` → 顶栏「管理台」→ 地址栏改到 `/ext/admin`，
即可看到「活动年级限定」「学生年级」「模拟邮件投递记录」三块面板。

演示账号：`student1`（大一，应被年级限定活动拒绝）、`student2`（大三，通过）、
`student3`（大二，通过），密码均为 `123456`。

## 验证

```bash
python -m pytest -q    # 58 passed：原有 25 + 本轮新增 33
python smoke_v2.py     # HTTP 链路冒烟：扩展蓝图 / 年级拒绝 / 等价性
```

## 两个入口

| 入口 | 说明 |
|---|---|
| `wsgi:app` | 变更前的应用，`wsgi.py` 原样保留，用于对照 |
| `app_v2:app` | 本轮交付，装配了 CR-01 / CR-02 |

生产环境（SQLite 单写者，worker 必须为 1）：

```bash
gunicorn -w 1 --threads 4 app_v2:app
```

## 文档

| 文档 | 内容 |
|---|---|
| `docs/06-CR01-CR02-变更影响分析-v2.md` | 影响分析（材料要求"先交影响分析"）：受影响构件、预计 vs 实际、有意差异、被否决方案、遗留风险 |
| `docs/07-增量设计与开闭原则论证-v2.md` | 设计决策、类图/时序、五个扩展点、OCP 自评与其限度 |
| `docs/08-回归测试表-v2.md` | CR1-01~05 / CR2-01~05 与测试函数一一映射、原有 25 例清单、改动范围证据 |

## 新增文件清单

```
app_v2.py                            扩展版 WSGI 入口
seed_ext_v2.py                       扩展演示数据
smoke_v2.py                          HTTP 冒烟检查
ext_v2/
  __init__.py                        包说明（文件名框架固定）
  schema_v2.py                       加列加表迁移（幂等）
  grade_v2.py                        年级准入规则 + 仓储
  email_v2.py                        MockEmailSender + 邮件监听器
  bus_v2.py                          扩展事件总线装配
  services_v2.py                     服务子类（报名/活动）
  routes_v2.py                       扩展管理蓝图
  factory_v2.py                      扩展应用工厂
  bootstrap_v2.py                    组合根接线（迁移 + 蓝图 + 注入）
  templates/ext_admin-v2.html        扩展管理页
tests/
  conftest.py                        恢复（main 中被误删，非本轮功能）
  ext_support_v2.py                  测试公共构造
  test_cr01_grade_v2.py              24 个 CR-01 用例
  test_cr02_email_v2.py              9 个 CR-02 用例
docs/06..08-*-v2.md                  三份文档
```

命名说明：代码文件用 `_v2`、文档与模板用 `-v2`（Python 模块名不能含连字符）。
`__init__.py` 与 `conftest.py` 是框架硬编码文件名，无法改名。

## 注意

- 仓库上一轮已有一组编号为 CR-01/CR-02 的变更（抽签 + email 入队），内容与本轮**无关**。
  本轮保留其功能，作为新一轮增量叠加，详见影响分析 §0。
- `main` 分支原本缺少 `tests/conftest.py`，25 个原有用例全部无法运行。
  本目录已恢复该文件，基线回归才可验证。
