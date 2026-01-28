# Python Marketplace SaaS Fulfillment MVP (FastAPI)

这是一个最小可用（MVP）的 **Marketplace SaaS Fulfillment** 服务端示例，用来覆盖从购买跳转到落地页、resolve/activate，到 webhook 回调落库的完整闭环。

你可以把它理解为“我方服务端”（ISV 侧）的一个 demo：

- 用户在 Marketplace 购买后，会被重定向到你的 Landing Page（带 `token`）
- 你用该 `token` 调用 Fulfillment Resolve，拿到 `subscriptionId`
- 你（或你的业务逻辑）对该订阅执行 Activate
- Marketplace 后续会用 Webhook 把状态变化事件回调给你

## 功能一览

核心端点：

- Landing Page：`GET /landing?token=...`
- Resolve：`POST /api/resolve`
- Activate：`POST /api/activate`
- Webhook：`POST /api/webhook`
- Admin（最小可用管理页）：`GET /admin`

数据持久化：

- SQLite（订阅表 + token 映射表 + webhook 事件表）

运行模式：

- `MARKETPLACE_MODE=mock`（默认）：不调用外部 Marketplace API，返回可演示的模拟数据
- `MARKETPLACE_MODE=live`：调用真实的 Microsoft Marketplace Fulfillment API（需要 Entra 应用凭据）

说明：在 `mock` 模式下，`subscriptionId` 是一个**由传入 token 推导出来的确定性 UUID**（便于重复测试/对比）。

## 配置（环境变量）

通用：

- `MARKETPLACE_MODE`：`mock` 或 `live`
- `DATABASE_PATH`：SQLite 文件路径（建议写到项目目录下的 `.tmp`，便于查看与清理）
- `ADMIN_ENABLED`：`true/false`（可选；详见 Admin 章节）

Live 模式（仅在 `MARKETPLACE_MODE=live` 使用）：

- `ENTRA_TENANT_ID`
- `ENTRA_CLIENT_ID`
- `ENTRA_CLIENT_SECRET`
- `MARKETPLACE_API_BASE`（默认 `https://marketplaceapi.microsoft.com`）
- `MARKETPLACE_API_VERSION`（默认 `2018-08-31`）

## 1) 本地运行（mock 模式）

```powershell
cd ms-mkp-py-mvp
..\.venv\Scripts\python -m pip install -r requirements.txt

$env:MARKETPLACE_MODE='mock'
New-Item -ItemType Directory -Force "$PWD\.tmp" | Out-Null
$env:DATABASE_PATH="$PWD\.tmp\ms-mkp-py-mvp.db"

..\.venv\Scripts\uvicorn app.main:app --reload
```

快速验证：

- `http://127.0.0.1:8000/healthz`
- `http://127.0.0.1:8000/landing?token=demo-token`

## 2) 端到端模拟操作（mock 模式）

下面这些步骤是“从头到尾”的最小链路，全部在本地完成，不依赖外部 Marketplace。

### 2.1 模拟用户访问 Landing Page

Landing Page 会读取 `token` 并触发 resolve（mock 模式下会生成订阅）。

打开浏览器：

`http://127.0.0.1:8000/landing?token=demo-token`

你会看到订阅信息（含 subscriptionId 和 status）。

### 2.2 直接调用 Resolve API（可选）

```powershell
$resp = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/resolve" -ContentType "application/json" -Body '{"token":"demo-token"}'
$resp | ConvertTo-Json -Depth 20
```

预期：返回 `subscriptionId`，以及 `cached` 字段（重复 resolve 会变成 `cached: true`）。

### 2.3 调用 Activate

```powershell
$subId = $resp.subscriptionId

$act = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/activate" -ContentType "application/json" -Body ("{\"subscriptionId\":\"$subId\"}")
$act | ConvertTo-Json -Depth 10
```

预期：订阅状态会被更新为 `Subscribed`（同时 `subscriptions` 表的 status 会变化）。

### 2.4 模拟 Marketplace Webhook 回调

服务会把 webhook 全量 payload 写入 `webhook_events` 表，并尝试从 payload 里提取状态更新订阅。

```powershell
$body = @'
{
  "subscriptionId": "REPLACE_ME",
  "action": "ChangePlan",
  "status": "Suspended",
  "note": "demo webhook"
}
'@
$body = $body.Replace("REPLACE_ME", $subId)

$wh = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/webhook" -ContentType "application/json" -Body $body
$wh | ConvertTo-Json
```

预期：返回 `{ "ok": true }`，并在 DB 里新增一条 webhook event，同时订阅状态会变为 `Suspended`。

### 2.5 如何查看 DB

SQLite 文件在你设置的 `DATABASE_PATH`：例如 `$PWD\.tmp\ms-mkp-py-mvp.db`。

表结构：

- `subscriptions`
- `marketplace_tokens`
- `webhook_events`

你可以用任意 SQLite 工具查看（例如 DB Browser for SQLite、或 VS Code 的 SQLite 扩展）。

## 3) Admin Portal（最小可用）

访问：`http://127.0.0.1:8000/admin`

能力：

- 列出 subscriptions
- 列出 webhook events（默认不拉取 payload，可在 API 中打开）
- 手动更新订阅 status
- 页面底部显示 Raw JSON，便于复制/排查

默认开关策略：

- `MARKETPLACE_MODE=mock`：默认开启
- `MARKETPLACE_MODE=live`：默认关闭（避免误暴露）

如需强制开/关：

```powershell
$env:ADMIN_ENABLED='true'  # 或 'false'
```

注意：Admin 页面没有做认证/授权，只适合本地或受控环境（demo/dev）。线上环境建议保持关闭，或自行加反向代理鉴权与网络访问控制。

Admin API（给页面调用，也可以直接 curl/Invoke）：

- `GET /admin/api/subscriptions?limit=50&offset=0&subscriptionId=...`
- `GET /admin/api/subscriptions/{subscriptionId}`
- `POST /admin/api/subscriptions/{subscriptionId}/status` body: `{ "status": "Suspended" }`
- `GET /admin/api/webhook-events?limit=50&offset=0&subscriptionId=...&includePayload=false`

## 4) 本地用 Docker 运行（更贴近 ACA 形态）

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
- `http://127.0.0.1:8000/admin`

## 5) 运行测试

```powershell
cd ms-mkp-py-mvp
..\.venv\Scripts\python -m pytest -q
```

## 6) 部署到 Azure Container Apps（ACA）

部署有两种方式：

1) 一键脚本（推荐）：`scripts/deploy-aca.ps1`
2) 手动命令参考：`docs/deploy-azure-container-apps.md`

### 6.1 前置条件

- 已安装并登录 Azure CLI：`az login`
- 本机 Docker Desktop 正常运行
- 具备创建 Resource Group / ACR / Container Apps 的权限

### 6.2 一键部署（mock 模式）

在项目目录执行：

```powershell
cd ms-mkp-py-mvp

./scripts/deploy-aca.ps1 \
  -ResourceGroup "rg-saas-mvp" \
  -Location "eastus" \
  -AcrName "acrsaaSmvp123" \
  -ContainerAppsEnvName "cae-saas-mvp" \
  -ContainerAppName "ca-saas-mvp" \
  -ImageTag "1" \
  -MarketplaceMode "mock"
```

脚本会：

- 创建/复用 RG、ACR、ACA 环境
- build 并 push 镜像到 ACR
- 创建/更新 Container App（对外 ingress，端口 8000）
- 最后打印 Partner Center 配置 checklist（Landing/Webhook URL 等）

部署完成后，脚本会打印可直接点开的 URL（含 `/healthz` 与 `/landing?token=demo-token`）。

### 6.3 一键部署（live 模式）

live 模式需要 Entra 应用凭据（client credentials）来调用真实 Fulfillment API。

```powershell
cd ms-mkp-py-mvp

./scripts/deploy-aca.ps1 \
  -ResourceGroup "rg-saas-mvp" \
  -Location "eastus" \
  -AcrName "acrsaaSmvp123" \
  -ContainerAppsEnvName "cae-saas-mvp" \
  -ContainerAppName "ca-saas-mvp" \
  -ImageTag "1" \
  -MarketplaceMode "live" \
  -TenantId "<ENTRA_TENANT_ID>" \
  -ClientId "<ENTRA_CLIENT_ID>" \
  -ClientSecret "<ENTRA_CLIENT_SECRET>"
```

脚本会把 `ClientSecret` 写入 ACA 的 secret（`entra-client-secret`），并以 `secretref:` 的方式注入环境变量。

注意：`MARKETPLACE_MODE=live` 时，Admin 默认关闭；如需开启请额外设置 `ADMIN_ENABLED=true`（不建议在公网环境开启）。

### 6.4 Partner Center 配置要填什么？

部署脚本会输出类似：

- Landing Page URL：`https://<fqdn>/landing`
- Webhook URL：`https://<fqdn>/api/webhook`
- （live 模式）Tenant ID / Client ID

把这些填到 Partner Center 的 SaaS Technical Configuration 对应位置即可。

### 6.5 查看日志

```powershell
az containerapp logs show -g rg-saas-mvp -n ca-saas-mvp --follow
```

## 7) 清理（可选）

本地：

```powershell
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "$PWD\.tmp"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue .pytest_cache
Remove-Item -ErrorAction SilentlyContinue Env:MARKETPLACE_MODE
Remove-Item -ErrorAction SilentlyContinue Env:DATABASE_PATH
Remove-Item -ErrorAction SilentlyContinue Env:ADMIN_ENABLED
```

Azure（谨慎）：删除整个资源组会清掉 ACR/ACA 等全部资源：

```powershell
az group delete -n rg-saas-mvp -y
```

## 常见问题

### PowerShell 里不要用多行 curl.exe（容易踩坑）

建议优先使用 `Invoke-RestMethod`（上面所有示例都是它）。

### live 模式 resolve/activate 失败

- 检查 `ENTRA_TENANT_ID/ENTRA_CLIENT_ID/ENTRA_CLIENT_SECRET` 是否正确
- 确认 Entra 应用具备调用 Fulfillment 所需权限/配置
- 打开 ACA 日志看具体错误

## 参考文档

- Landing page token + resolve: https://learn.microsoft.com/partner-center/marketplace-offers/azure-ad-transactable-saas-landing-page
- SaaS fulfillment subscription APIs v2: https://learn.microsoft.com/partner-center/marketplace-offers/pc-saas-fulfillment-subscription-api
