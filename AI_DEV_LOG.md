# AI_DEV_LOG

记录与 AI 协作中的关键事件，重点写"AI 给了什么、我做了什么判断"。按附录 D.2 的四列格式，5–10 条。

> 说明：下表由本轮实现过程整理，时间与 commit 号需在本地实际提交后回填。

| 时间 / 版本 | 任务与发给 AI 的关键指令 | AI 产出与问题 | 学生判断 / 验证 |
|---|---|---|---|
| 11-19 / init | 按已评审类图实现 `RegistrationPolicy` 接口与直接/审核两种实现 | AI 把"名额是否已满"也写进了策略的 `decide()`，两种实现各写了一遍 | 否决。名额是公共不变量，与报名方式无关，两条策略重复实现会违反 DRY/SRP。要求把校验上移到 `RegistrationService.register()`，策略只返回初始状态。用 C4/C8 两个用例验证 |
| 11-19 / policies | 实现报名主流程 `RegistrationService.register()` | AI 直接在事务里写 `message` 表，没有事件层 | 否决。任务 C 要求业务与通知解耦。改为 `publisher.publish()`，由 `InAppNotificationListener` 写消息 |
| 11-19 / events | 处理"通知失败会不会影响报名" | AI 把 publish 放在 commit 之前，监听器异常会连带回滚报名 | 修正为"先 commit 再 publish"，并让 `SimpleEventBus` 捕获监听器异常、写 `notify_outbox` 留痕。新增 `test_notification_failure_does_not_rollback_registration` 验证 |
| 11-19 / unique | 防止同一学生重复报名 | AI 只在服务层 `if 已存在 then return`，没有数据库约束 | 追加部分唯一索引 `ux_active_registration`，服务层捕获 `IntegrityError` 兜底；新增 `test_unique_index_blocks_second_active_registration` |
| 11-19 / notify | 避免同一事件重复发通知 | AI 用 `message_id` 自增去重，重复投递仍会新增一条 | 改为业务键 `event_id` 去重：`message` 表 `UNIQUE(event_id, student_id)` + `INSERT OR IGNORE`；新增幂等测试 |
| 11-19 / cancel | 实现取消后再报名 | AI 复用原记录做 `UPDATE status` | 否决。B.2 第 4 条要求"保留历史、允许再次申请"。改为新增一条记录，原记录保持 `CANCELLED`；`test_cancelled_registration_can_apply_again` 验证 |
| 11-19 / delete | 实现活动删除 | AI 用 `ON DELETE CASCADE` 级联删掉报名与通知 | 否决。会导致报名与通知历史静默消失。改为"有报名则拒绝删除并提示关闭活动"，`test_delete_activity_with_registrations_is_refused` 验证 |
| 11-19 / authz | 管理台权限控制 | AI 只在模板里 `{% if me.is_admin %}` 隐藏入口，直接访问 `/admin/` 仍可进入 | 追加 `@admin_required` 装饰器返回 403，并用 `test_student_cannot_open_admin_page` 验证"隐藏按钮 ≠ 权限控制" |
| 11-19 / redirect | 登录后跳回原页面 | AI 直接 `redirect(request.args["next"])`，存在开放重定向 | 增加 `_safe_next()` 只允许站内相对路径；`test_open_redirect_is_blocked` 验证 |

## 过程中形成的约定

1. **设计先行**：类图定稿并评审签字后，才允许 AI 生成实现代码；AI 输出的类名必须与类图一致。
2. **AI 的建议要过设计原则这一关**：上表 9 条里有 6 条否决了 AI 的默认做法，理由都能落到 SOLID 或需求条款上。
3. **每条业务规则至少有一个测试守住**：新增规则先写用例再落代码。
