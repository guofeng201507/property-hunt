# Deployment

部署目标：Ubuntu 24.04 服务器，Nginx 80 端口 + Basic Auth，Streamlit 只监听本机 8501。

## 1. 准备配置

```bash
cp deploy/.deploy.env.example deploy/.deploy.env
chmod 600 deploy/.deploy.env
```

编辑 `deploy/.deploy.env`：

```bash
DEPLOY_HOST=your-server-ip
DEPLOY_USER=root
SSH_KEY=/absolute/path/to/your-key.pem
APP_DIR=/opt/property-hunt
REPO_URL=https://github.com/guofeng201507/property-hunt.git
APP_DOMAIN=properties.example.com
LETSENCRYPT_EMAIL=you@example.com
BASIC_AUTH_USER=feng
BASIC_AUTH_PASS=change-me-to-a-long-random-password
```

`APP_DOMAIN` 和 `LETSENCRYPT_EMAIL` 可选。填了之后 bootstrap 会自动用 Certbot 申请 Let's Encrypt 证书并配置 HTTPS。DNS 的 A 记录必须指向 `DEPLOY_HOST`，安全组需要放行 80 和 443。

`deploy/.deploy.env` 已在 `.gitignore` 中，不会提交。

本地需要：`ssh`、`rsync`、`sqlite3`、`curl`。  
服务器需要：root SSH、Ubuntu 24.04、Python 3.11+（bootstrap 会安装 `python3-venv`）。

## 2. 执行部署

```bash
./deploy/deploy.sh
```

脚本会：

1. 用 `sqlite3 .backup` 生成本地 SQLite 一致快照
2. 上传 `db/property.db`
3. 上传 `.env`（URA_ACCESS_KEY）
4. 上传 `data/geo/`（MP2025 / 地籍 / MRT，如果存在）
5. 在服务器执行 `deploy/bootstrap.sh`：
   - 安装 nginx、rsync、python3-venv 等
   - 确保 2GB swap
   - clone/pull 代码
   - 创建 venv 并安装依赖
   - 创建 `property` 运行用户
   - 写 systemd service
   - 写 Nginx 反代 + Basic Auth
   - 重启服务
6. 用 Basic Auth 做公网 `curl` 检查

脚本是幂等的，可重复执行用于更新代码或数据。

## 3. 手动验证

```bash
ssh -i "$SSH_KEY" "$DEPLOY_USER@$DEPLOY_HOST" \
  'systemctl is-active property-hunt && systemctl is-active nginx'

curl -u "$BASIC_AUTH_USER:$BASIC_AUTH_PASS" \
  -o /dev/null -w '%{http_code}\n' "http://$DEPLOY_HOST/"
```

预期：

```text
active
active
200
```

## 4. 远程 MCP

服务器不暴露 MCP 端口。Qoder / Codex 用 SSH stdio 接入：

```json
{
  "mcpServers": {
    "property-hunt": {
      "command": "ssh",
      "args": [
        "-i", "/absolute/path/to/your-key.pem",
        "-T", "-o", "LogLevel=ERROR",
        "root@your-server-ip",
        "cd /opt/property-hunt && .venv/bin/python -m property_hunt.mcp_server"
      ]
    }
  }
}
```

## 5. 刷新数据

当前 bootstrap 不自动加定时任务。手动刷新：

```bash
ssh -i "$SSH_KEY" "$DEPLOY_USER@$DEPLOY_HOST" \
  'cd /opt/property-hunt && .venv/bin/python scripts/run_ingest.py --mode live --dataset planning'
```

注意：`run_ingest.py` 在 geo 图层存在时会重新做空间富化，1.6GB 内存的机器建议低峰期执行，或先在本地刷新 DB 后再跑 `./deploy/deploy.sh` 同步。

## 6. HTTPS

在 `deploy/.deploy.env` 中设置：

```bash
APP_DOMAIN=properties.example.com
LETSENCRYPT_EMAIL=you@example.com
```

确保：

- 域名 A 记录指向 `DEPLOY_HOST`
- 阿里云安全组放行 80 和 443
- `deploy/.deploy.env` 权限为 600

bootstrap 首次部署会先写 HTTP 配置，再运行 `certbot --nginx` 申请证书；后续部署如果检测到证书已存在，会直接写 HTTPS 配置，不会把 SSL 覆盖掉。Certbot 会自动安装续期 timer。

## 文件

- `deploy/deploy.sh`：本地编排脚本
- `deploy/bootstrap.sh`：服务器初始化脚本
- `deploy/.deploy.env.example`：配置模板
