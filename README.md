# CampusEvent — 校园活动报名与管理系统

《软件工程》课程实践 实验二。学生先完成面向对象设计（策略模式 + 观察者模式），再由 AI 辅助按设计实现，最后应对需求变更并做回归测试。

- 技术栈：Python 3.11+ / Flask 3 / SQLite / pytest
- 架构：界面（Jinja2 页面）→ 应用服务 → 仓储 → SQLite，报名规则用策略模式隔离，通知用观察者模式解耦

## 1. 快速开始

```bash
cd CampusEvent

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

python seed.py     # 重建演示数据（会删除 instance/campusevent.sqlite3）
python wsgi.py     # 或 python -m flask --app wsgi run --port 5000
```

浏览器打开 <http://127.0.0.1:5000>

### 演示账号

| 账号 | 密码 | 角色 |
|------|------|------|
| admin | admin123 | 管理员 |
| student1 | 123456 | 学生（张三） |
| student2 | 123456 | 学生（李四） |
| student3 | 123456 | 学生（王五） |

演示数据包含：已满员的直接报名活动、审核型活动（含待审核申请）、已开始的活动、已关闭的活动。

## 2. 运行测试

```bash
python -m pytest -q
```

当前用例覆盖指导书 3.5 的 C1–C10 与 B.2 的边界规则，映射关系见 `docs/08-回归测试表.md`。

## 3. 目录结构

```
CampusEvent/
├─ app/
│  ├─ __init__.py        应用工厂，集中装配依赖
│  ├─ db.py              连接管理 + 建表 + 部分唯一索引
│  ├─ models.py          实体、枚举、Result、错误码
│  ├─ repositories.py    仓储层（全部 SQL）
│  ├─ policies.py        报名策略接口 + 直接/审核两种实现 + 工厂
│  ├─ events.py          领域事件、事件总线、站内通知/审计监听器
│  ├─ services.py        报名与审批用例（不变量集中校验）
│  ├─ routes/            学生端、管理端、登录
│  ├─ templates/         Jinja2 模板
│  └─ static/style.css
├─ tests/                pytest 用例
├─ docs/                 SRS、UML、变更影响分析、实验报告
├─ seed.py               演示数据
├─ wsgi.py               WSGI 入口
├─ requirements.txt
└─ AI_DEV_LOG.md
```

## 4. 设计说明

### 4.1 职责划分

| 层 | 类 | 责任 |
|----|----|------|
| 界面 | `routes/student.py`、`routes/admin.py` | 接收请求、渲染页面、展示业务结果 |
| 应用服务 | `RegistrationService` | 校验不变量、编排策略与事件、事务边界 |
| 策略 | `RegistrationPolicy`（→ `Direct` / `Review`） | 只决定"这一笔申请置为何种状态" |
| 事件 | `SimpleEventBus` + `InAppNotificationListener` | 把报名结果转成站内消息 |
| 仓储 | `*Repository` | 所有 SQL，含统计聚合 |
| 实体 | `Activity` / `Student` / `Registration` / `Message` | 纯数据 |

### 4.2 三个关键设计决策

**(1) 名额检查属于公共规则，不属于策略。**

`register()` 在调用策略之前统一校验：活动存在 → 未关闭 → 未开始 → 无重复有效报名 → 名额未满。理由是这些条件与"报名方式"无关，报名和审批两条路径都要用，而且名额需要数据库聚合计数。若写进策略，两种实现会重复代码，新增第三种策略还要再写一遍。

**(2) 事件在事务提交之后发布。**

`RegistrationService` 先 `commit()` 报名，再 `publisher.publish(event)`。监听器抛异常时被 `SimpleEventBus` 捕获，写 `notify_outbox`（状态 `FAILED` + 错误信息）留痕，报名记录不受影响——满足 B.2 第 6 条"通知失败应留痕，但不得导致报名无声消失"。

**(3) 重复通知用 event_id 幂等，不靠人工判断。**

`message` 表 `UNIQUE(event_id, student_id)` + `INSERT OR IGNORE`，`notify_outbox` 表 `UNIQUE(event_id, listener)`。同一事件重复投递只产生一条消息。

### 4.3 数据库层的兜底

```sql
CREATE UNIQUE INDEX ux_active_registration
    ON registration(activity_id, student_id)
    WHERE status IN ('PENDING', 'APPROVED');
```

应用层先查重是"友好提示"，真正的正确性保证在这个部分唯一索引上：并发下两条有效报名只可能成功一条，服务层捕获 `IntegrityError` 后返回 `DUPLICATE_ACTIVE`。已取消/已拒绝的历史记录不受该索引约束，因此可以再次申请。

### 4.4 错误码

`app/models.py::ErrorCode` 与页面提示一一对应，便于测试断言：`DUPLICATE_ACTIVE`、`CAPACITY_FULL`、`ACTIVITY_STARTED`、`ACTIVITY_CLOSED`、`INVALID_STATE`、`FORBIDDEN`、`VALIDATION_ERROR` 等。

## 5. 业务规则实现情况

| 规则（附录 B.2） | 实现位置 |
|---|---|
| 直接报名自动通过 + 通知 | `DirectRegistrationPolicy` + `InAppNotificationListener` |
| 审核型进入待审核 | `ReviewRegistrationPolicy` |
| 名额只按"已通过"计算 | `RegistrationService.register / approve` |
| 满员后不得批准 | `approve()` 二次校验（用例 C8） |
| 同一活动不得两条有效报名 | 服务层查重 + 部分唯一索引 |
| 取消待审核/已通过报名 | `cancel()`，状态置 `CANCELLED` 并通知 |
| 活动开始后不允许报名 | `register()` 比对 `start_at` |
| 通知失败留痕且不回滚报名 | 事务提交后发布 + `notify_outbox` |
| 删除有报名的活动 | 拒绝删除并提示改为关闭（`ActivityService.delete`） |

## 6. 设计假设

| 编号 | 假设 | 理由 |
|---|---|---|
| A-1 | 满员后**不接受**任何新申请，包括审核型 | 待审核不占名额，仍允许申请会堆积大量注定失败的申请；B.2 第 3 条也要求满员后不得批准 |
| A-2 | 活动开始后仍可取消已通过的报名 | B.2 只禁止"新增报名"，未禁止取消；取消属于学生自主权利 |
| A-3 | 删除有报名的活动采用"拒绝删除"，不做软删除 | 实现成本低、语义明确；软删除需要处理唯一索引与统计口径 |
| A-4 | 演示账号为固定账号，密码明文比对 | 附录 B.1 允许固定演示账号；生产环境应改为哈希存储 |

## 7. 部署

```bash
pip install -r requirements.txt gunicorn
gunicorn -w 2 -b 0.0.0.0:5000 wsgi:app
```

- 云服务器需在安全组放行 5000 端口；访问地址写入本文件末尾。
- SQLite 文件位于 `instance/`，必须落在持久磁盘上（静态托管、云函数等无持久文件系统的环境不适用）。
- 生产环境请通过环境变量覆盖 `SECRET_KEY` 与 `DATABASE_PATH`。

**公网访问地址**：（部署后填写）

## 8. 已知限制

- 未做并发压力测试，SQLite 写并发依赖单写者锁；生产应换 MySQL/PostgreSQL。
- 通知为站内消息，未接真实邮件/短信通道。
- 变更 CR-01/02/03 的实现在 `change-v2` 分支，见 `docs/09-变更影响分析.md`。
