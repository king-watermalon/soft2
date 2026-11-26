# CampusEvent 云服务器部署手册

目标实例：腾讯云 CVM `标准型S5` / 上海二区 / 2核 2GiB / 3Mbps
公网 IP：`43.142.191.108`

最终形态：浏览器访问 `http://43.142.191.108` → Nginx(80) → Gunicorn(127.0.0.1:5000) → Flask → SQLite

---

## 0. 先确认三件事

| 项目 | 怎么查 | 影响 |
|---|---|---|
| 操作系统 | 控制台实例列表 → 操作系统列 | 决定用 `apt` 还是 `dnf`。本文按 Ubuntu 22.04/24.04 写 |
| 登录方式 | 创建实例时选了「密码」还是「密钥」 | 决定用密码登录还是 `.pem` 文件 |
| 安全组 | 控制台 → 安全组 → 入站规则 | 必须放行 22、80 |

> 大陆地域（上海）的服务器：**直接用 IP 访问 80 端口不需要备案**；一旦要把域名解析到这台机器，域名必须先完成 ICP 备案，否则会被拦截。

---

## 1. 连接服务器

### 方式 A：网页终端（最快，先解决"进不去"）

控制台实例列表右侧「登录」按钮 → 选「标准登录方式(WebShell)」→ 直接在浏览器里打开一个 root 终端。
如果提示没有密码或密码未知：实例右键「更多 → 密码/密钥 → 重置密码」，设置后**必须重启实例**才生效。

### 方式 B：本地 SSH（Windows 10+ 自带 OpenSSH）

在 PowerShell 里执行：

```powershell
ssh root@43.142.191.108
```

首次连接会问 `Are you sure you want to continue connecting?`，输入 `yes`，然后输入实例密码（输入时不显示字符，属正常）。

用密钥对时：

```powershell
ssh -i C:\path\to\key.pem root@43.142.191.108
```

若报 `WARNING: UNPROTECTED PRIVATE KEY FILE`（权限过宽），在 PowerShell 里收紧权限：

```powershell
icacls key.pem /inheritance:r
icacls key.pem /grant:r "$($env:USERNAME):(R)"
```

### 方式 C：日常开发用普通用户（推荐，但可选）

```bash
adduser dev && usermod -aG sudo dev
```

之后用 `ssh dev@43.142.191.108`，需要 root 权限时加 `sudo`。

> 连不上先查安全组 22 端口，再查 `systemctl status ssh`。腾讯云默认镜像一般已放行 22。

---

## 2. 装基础环境

```bash
apt update && apt install -y python3 python3-venv python3-pip nginx git
python3 -V          # 应为 3.10 以上
```

CentOS / OpenCloudOS 镜像则把 `apt install` 换成 `dnf install -y python3 python3-pip nginx`。

---

## 3. 把代码传上去

目标路径统一用 `/opt/CampusEvent`。

### 3.1 传到服务器（在你的 Windows 本机执行，不是服务器上）

在项目**上一级**目录（即 `实验二` 目录）打开 PowerShell：

```powershell
scp -r .\CampusEvent root@43.142.191.108:/opt/
```

注意：**不要**把本地的 `.venv/`、`.pytest_cache/`、`instance/*.sqlite3` 一起传上去（平台不同、数据会被演示数据覆盖）。想干净传输可以先在本机删掉这三个，或用 Git。

### 3.2 或走 Git（更可重复）

```bash
# 服务器上
cd /opt && git clone <你的仓库地址> CampusEvent
```

---

## 4. 启动应用

本目录已提供三份现成配置，直接复用即可：

| 文件 | 用途 |
|---|---|
| `deploy/deploy.sh` | 一键部署脚本（装依赖 → 跑测试 → 建库 → 装 systemd/nginx → 启动） |
| `deploy/campusevent.service` | systemd 守护单元，进程挂了自动拉起 |
| `deploy/nginx-campusevent.conf` | Nginx 反向代理 + 静态资源直出 |

### 4.1 一键部署（推荐）

```bash
cd /opt/CampusEvent
bash deploy/deploy.sh
```

脚本会依次做：装包 → 建 venv 装 requirements → 跑 pytest（失败就停）→ `seed.py` 建演示库到 `/var/lib/campusevent/` → `chown www-data` → 装并启动 systemd 与 nginx。

### 4.2 手动逐步（想搞清每一步时用）

```bash
cd /opt/CampusEvent
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# 先生成演示数据，再交给 www-data
mkdir -p /var/lib/campusevent
chown -R www-data:www-data /opt/CampusEvent /var/lib/campusevent
sudo -u www-data env DATABASE_PATH=/var/lib/campusevent/campusevent.sqlite3 \
    ./.venv/bin/python seed.py

# 守护进程
cp deploy/campusevent.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now campusevent

# 反向代理
cp deploy/nginx-campusevent.conf /etc/nginx/sites-available/campusevent.conf
ln -sf /etc/nginx/sites-available/campusevent.conf /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

### 4.3 先改掉默认 SECRET_KEY

`deploy/campusevent.service` 里的 `CHANGE_ME_TO_A_LONG_RANDOM_STRING` 必须换成随机串：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

把输出粘进 `/etc/systemd/system/campusevent.service` 的 `Environment="SECRET_KEY=..."`，然后 `systemctl daemon-reload && systemctl restart campusevent`。

---

## 5. 放行端口（不做这步，外网一定打不开）

腾讯云控制台 → 实例 → 右侧「更多」→「安全组」→ 编辑规则 → 入站规则添加：

| 类型 | 协议端口 | 来源 |
|---|---|---|
| 自定义 | TCP:80 | 0.0.0.0/0 |
| 自定义 | TCP:443 | 0.0.0.0/0（上 HTTPS 后需要） |

**不要把 5000 端口对外开放**：gunicorn 只监听 `127.0.0.1:5000`，由 Nginx 转发，外部直接访问 5000 会被拒——这是有意为之。若服务器内部装了 ufw/firewalld，也要同步放行 80。

---

## 6. 验证

```bash
# 服务器内部
curl -I http://127.0.0.1/            # 期望 200 或 302
systemctl status campusevent         # active (running)
journalctl -u campusevent -n 50 --no-pager
```

浏览器打开 <http://43.142.191.108>，用 `admin/admin123` 或 `student1/123456` 登录。

三条链路逐段验证，哪段断了就查哪段：

1. `curl http://127.0.0.1:5000` 通 → Flask 活着
2. `curl http://127.0.0.1` 通 → Nginx 反代正常
3. 浏览器公网访问通 → 安全组放行正常

---

## 7. 日常运维

```bash
# 改完代码后更新
cd /opt/CampusEvent && git pull        # 或重新 scp
systemctl restart campusevent

# 看日志
journalctl -u campusevent -f
tail -f /var/log/nginx/error.log

# 备份数据（就一个 sqlite 文件）
cp /var/lib/campusevent/campusevent.sqlite3 ~/campusevent-$(date +%F).sqlite3
```

**重新灌演示数据**（会清空现有数据）：

```bash
systemctl stop campusevent
sudo -u www-data env DATABASE_PATH=/var/lib/campusevent/campusevent.sqlite3 \
    /opt/CampusEvent/.venv/bin/python /opt/CampusEvent/seed.py
systemctl start campusevent
```

---

## 8. 可选：绑域名 + HTTPS

前提：域名已完成 **ICP 备案**（大陆服务器硬性要求），并添加 A 记录指向 `43.142.191.108`。

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d your-domain.com     # 自动改写 nginx 配置并配好 443
```

`0.0.0.0/0` 来源的 443 已在第 5 步放行。证书 90 天自动续期，用 `certbot renew --dry-run` 验证。

---

## 9. 常见报错对照

| 现象 | 原因 | 处理 |
|---|---|---|
| 浏览器一直转圈/超时 | 安全组未放行 80 | 第 5 步 |
| `502 Bad Gateway` | gunicorn 没起来或崩了 | `journalctl -u campusevent -n 50` |
| `502` 且日志写 `Permission denied: ...sqlite3` | 数据库文件属主不是 www-data | `chown -R www-data:www-data /var/lib/campusevent` |
| 页面无样式 | `/static/` alias 路径错 | 确认 `ls /opt/CampusEvent/app/static/style.css` 存在 |
| `sqlite3.OperationalError: attempt to write a readonly database` | 上级目录缺写权限 | `chmod 755 /var/lib/campusevent`，属主置 www-data |
| 登录后立刻掉登录态 | `SECRET_KEY` 每次重启都变 / 未配置 | 固定 `SECRET_KEY` 后重启 |
| `ssh: connect to host ... port 22: Connection timed out` | 安全组 22 未放行，或实例未运行 | 控制台查实例状态与安全组 |
| 部署后中文变问号 | 未设置 locale（一般不影响，Flask 默认 UTF-8） | 检查模板文件传输是否损坏 |

---

## 10. 关于这台机器的容量

2核 2GiB + 3Mbps 带宽，跑这个课程项目绰绰有余：

- 2 个 gunicorn worker 常驻约占 150–250MB 内存，剩 1.5GB 以上余量。
- 3Mbps ≈ 375KB/s。首屏含 CSS 但几乎无图片，几十 KB 级别，秒开；并发多人时瓶颈是带宽而不是 CPU。
- SQLite 单写者锁：课程演示场景（个位数并发）没问题，真上生产要换 MySQL/PostgreSQL——这一点 README「已知限制」里已写明。
