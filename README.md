# Python SaaS Fulfillment MVP (FastAPI)

这是一个小而自包含的 MVP，用来覆盖 Microsoft Marketplace（商业市场）SaaS Fulfillment 的关键触点：

- Landing page（`/landing?token=...`）：接收 Marketplace 重定向带来的 `token` 并调用 resolve
- Resolve（`POST /api/resolve`）与 Activate（`POST /api/activate`）接口
- Webhook 接收端（`POST /api/webhook`）：记录事件
- SQLite 持久化（订阅 + webhook 事件）

支持两种运行模式：

- `MARKETPLACE_MODE=mock`（默认）：不调用外部 API，生成可用于演示/测试的数据
- `MARKETPLACE_MODE=live`：调用真实的 Microsoft Marketplace SaaS Fulfillment API（需要 Entra 应用凭据）

在 `mock` 模式下，`subscriptionId` 是一个**由传入 `token` 推导出来的确定性 UUID**，便于做可重复的验证（重启/换环境/空库都一致）。

## 本地运行

```powershell
cd ms-mkp-py-mvp
..\.venv\Scripts\python -m pip install -r requirements.txt
$env:MARKETPLACE_MODE='mock'
..\.venv\Scripts\uvicorn app.main:app --reload
```

Open:
- `http://127.0.0.1:8000/healthz`
- `http://127.0.0.1:8000/landing?token=demo-token`

访问：
- `http://127.0.0.1:8000/healthz`
- `http://127.0.0.1:8000/landing?token=demo-token`

## 本地用 Docker 运行（更贴近 ACA 运行形态）

说明：本地容器运行环境由 Docker Desktop/本机 Docker Engine 提供；本项目通过 `Dockerfile` 定义镜像如何构建。

1) 构建镜像

```powershell
cd ms-mkp-py-mvp
docker build -t ms-mkp-py-mvp:local .
```

2) 运行容器（mock 模式）

```powershell
docker run --rm -p 8000:8000 \
  -e MARKETPLACE_MODE=mock \
  -e DATABASE_PATH=/tmp/app.db \
  ms-mkp-py-mvp:local
```

3) 验证

- `http://127.0.0.1:8000/healthz`
- `http://127.0.0.1:8000/landing?token=demo-token`

## 运行测试

```powershell
cd ms-mkp-py-mvp
..\.venv\Scripts\python -m pytest -q
```

## 验证 mock 的“确定性”

1) 使用 `mock` 模式启动服务。
2) 使用相同 token 调用两次 resolve，但每次都使用一个全新的（空）数据库。

示例（PowerShell），使用两个不同的 DB 路径：

```powershell
$env:MARKETPLACE_MODE='mock'

$env:DATABASE_PATH="$PWD\\data\\db1.db"
..\.venv\Scripts\uvicorn app.main:app --reload
# 在另一个终端里：
# curl.exe -sS -X POST http://127.0.0.1:8000/api/resolve -H "Content-Type: application/json" -d '{"token":"same-token"}'

# 停止服务后，再：
$env:DATABASE_PATH="$PWD\\data\\db2.db"
..\.venv\Scripts\uvicorn app.main:app --reload
# 使用同一个 token 再调用一次 resolve。
```

对于同一个 `token`，返回的 `subscriptionId` 应该完全相同。

## Live 模式前置条件（概览）

- 具备 Marketplace Fulfillment 权限的 Entra ID 应用（client credentials）
- 设置环境变量：
  - `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`
  - `MARKETPLACE_MODE=live`

### 这三个变量是什么？

- `ENTRA_TENANT_ID`：Microsoft Entra 租户 ID（Tenant ID，GUID）。
- `ENTRA_CLIENT_ID`：Entra 应用注册的“应用程序(客户端) ID”（Client ID，GUID）。
- `ENTRA_CLIENT_SECRET`：上述应用的 Client Secret（只填 secret 的 value）。

### 从哪里获取？

在 Azure 门户：Microsoft Entra ID → **应用注册 (App registrations)** → 选择你的应用。

- `ENTRA_TENANT_ID`：概述（Overview）里的 **Directory (tenant) ID**。
- `ENTRA_CLIENT_ID`：概述（Overview）里的 **Application (client) ID**。
- `ENTRA_CLIENT_SECRET`：**Certificates & secrets** → 新建 **Client secret**，复制生成的 **Value**。

### 程序如何使用它们？

本服务在 `MARKETPLACE_MODE=live` 时会用 client credentials flow 向：

`https://login.microsoftonline.com/{ENTRA_TENANT_ID}`

申请访问令牌（scope 为 `https://marketplaceapi.microsoft.com/.default`），然后用该令牌调用 SaaS Fulfillment API（Resolve/Activate 等）。

### 安全建议

- 不要把真实的 `ENTRA_CLIENT_SECRET` 提交到代码库。
- 本地建议用环境变量或 `.env`（自行创建，不要 commit）。
- 部署到 ACA 时建议用 `az containerapp secret set` 保存 secret，并在环境变量中用 `secretref:` 引用（见部署文档）。

参考文档：
- Landing page 与 resolve token： https://learn.microsoft.com/partner-center/marketplace-offers/azure-ad-transactable-saas-landing-page
- SaaS fulfillment subscription APIs v2： https://learn.microsoft.com/partner-center/marketplace-offers/pc-saas-fulfillment-subscription-api
