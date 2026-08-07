# Kelivo File Maker MCP

给 Kelivo 使用的远程 MCP 文件生成器。模型写完代码后，可以直接生成 `.txt`、`.html` 或其他文本文件，并返回 HTTPS 下载链接。

## 已包含的工具

- `create_txt(filename, content)`：生成 TXT
- `create_html(filename, content)`：生成 HTML
- `create_pair(filename, content)`：用同一份源码同时生成 TXT + HTML
- `create_file(filename, content)`：生成 txt/html/htm/md/css/js/json/xml/csv/yaml/yml

默认文件保留 24 小时；每次生成使用随机 token，不会因为同名文件互相覆盖。

> Render Web Service 的本地文件系统是临时的。服务重启或重新部署后，旧下载文件可能提前消失。因此这个 MCP 适合“模型生成后立即下载”，不是长期网盘。

## 1. 上传到 GitHub

1. 解压本项目。
2. 打开 GitHub，新建一个仓库，例如 `kelivo-file-mcp`。
3. 在仓库页面选择 **Add file → Upload files**。
4. 把本项目根目录里的文件和文件夹全部上传。
5. Commit changes。

根目录应至少看到：

```text
file_store.py
server.py
requirements.txt
render.yaml
README.md
KELIVO_SYSTEM_PROMPT.txt
tests/
```

## 2. 部署到 Render

### 推荐：Blueprint

1. 登录 Render。
2. 连接你的 GitHub。
3. 选择 **New → Blueprint**。
4. 选择刚才的 `kelivo-file-mcp` 仓库。
5. Render 会读取根目录的 `render.yaml`。
6. 确认后创建服务并等待部署完成。

本项目的 Render 配置已经写好：

- Build Command：`pip install -r requirements.txt`
- Start Command：`uvicorn server:app --host 0.0.0.0 --port $PORT`
- Health Check：`/health`

### 如果不用 Blueprint

手动创建 **Web Service**，填写：

```text
Language: Python 3
Build Command: pip install -r requirements.txt
Start Command: uvicorn server:app --host 0.0.0.0 --port $PORT
Health Check Path: /health
```

## 3. 确认服务器正常

Render 部署完成后会给你一个地址，例如：

```text
https://kelivo-file-mcp.onrender.com
```

浏览器打开：

```text
https://kelivo-file-mcp.onrender.com/health
```

正常会看到类似：

```json
{
  "status": "ok",
  "service": "Kelivo File Maker MCP",
  "mcp": "/mcp",
  "ttl_hours": 24,
  "max_content_bytes": 3000000
}
```

## 4. 在 Kelivo 添加 MCP

MCP 类型选择 **Streamable HTTP**。

地址填写：

```text
https://你的Render地址.onrender.com/mcp
```

连接成功后，Kelivo 应能看到：

```text
create_txt
create_html
create_pair
create_file
```

## 5. 给 Kelivo 加系统提示词

项目里已经准备好：

```text
KELIVO_SYSTEM_PROMPT.txt
```

把里面的内容复制到你写代码的助手系统提示词中即可。

之后你可以直接说：

```text
把这个代码改好，给我完整 TXT。
```

或：

```text
改好后同时给我 HTML 和 TXT，两份源码必须完全一致。
```

模型就应该调用 MCP，而不是只在聊天框粘贴代码。

## 6. 文件保存规则

默认：

```text
FILE_TTL_HOURS=24
MAX_CONTENT_BYTES=3000000
```

Render 会自动提供 `RENDER_EXTERNAL_URL`，代码使用它生成下载链接，所以通常不需要自己填写域名。

如果以后绑定自己的域名，可以在 Render 环境变量里加入：

```text
PUBLIC_BASE_URL=https://你的域名
```

## 7. 本地测试（可选）

Python 3.10+：

```bash
pip install -r requirements-dev.txt
pytest -q
uvicorn server:app --host 127.0.0.1 --port 8000
```

打开：

```text
http://127.0.0.1:8000/health
```

本地 MCP：

```text
http://127.0.0.1:8000/mcp
```

## 为什么文件限制为 3 MB

MCP Streamable HTTP 默认请求体限制约为 4 MiB。给 `content` 保留协议封装余量后，本项目默认限制为 3,000,000 bytes，更适合直接生成代码和文本文件。
