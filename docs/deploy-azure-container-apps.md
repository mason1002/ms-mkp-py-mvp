# 部署到 Azure Container Apps（ACA）

本文档演示如何使用 **Azure Container Registry（ACR）** + **Azure Container Apps（ACA）** 部署本 Python MVP。

## 前置条件

- 已安装并登录 Azure CLI（`az`）：`az login`
- 本机 Docker Desktop 正常运行
- 具备创建 Resource Group / ACR / Container Apps 的权限

## 1) 命名规划

需要全局唯一的资源（如 ACR）请确保名称不冲突。

```powershell
$RG = "rg-saas-mvp"
$LOC = "eastus"
$ACR = "acrsaaSmvp"      # must be globally unique
$ENV = "cae-saas-mvp"    # Container Apps environment
$APP = "ca-saas-mvp"     # Container App name
$IMAGE = "$ACR.azurecr.io/marketplace-saas-mvp:1"
```

## 2) Create resource group + ACR

## 2) 创建资源组与 ACR

> ⚠️ 注意：从这里开始执行 `az group create` / `az acr create` 会在你的 Azure 订阅里**真实创建资源**（Resource Group、ACR），并可能产生费用（ACR 存储/出入站等）。请先确认当前登录的订阅与账号。

```powershell
az group create -n $RG -l $LOC

az acr create -g $RG -n $ACR --sku Basic
az acr login -n $ACR
```

## 3) Build and push the container image

在仓库根目录执行：

```powershell
cd ms-mkp-py-mvp

docker build -t $IMAGE .
docker push $IMAGE
```

替代方案：使用 ACR 远程构建（无需本地 Docker build）：

```powershell
az acr build -g $RG -r $ACR -t marketplace-saas-mvp:1 .
```

## 4) Create a Container Apps environment

## 4) 创建 Container Apps 环境

> ⚠️ 注意：执行 `az containerapp env create` 会创建 ACA Environment（以及相关的监控/日志依赖资源），开始产生持续费用。

```powershell
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az extension add --name containerapp --upgrade

az containerapp env create -g $RG -n $ENV -l $LOC
```

## 5) Create the Container App

## 5) 创建 Container App

> ⚠️ 注意：执行 `az containerapp create` 会创建对公网暴露的真实服务（Container App）。运行实例、日志等都会产生费用；不使用时建议按 README 的清理章节删除整个资源组。

### Mock mode (no external Marketplace calls)

### Mock 模式（不调用外部 Marketplace API）

```powershell
az containerapp create \
  -g $RG -n $APP --environment $ENV \
  --image $IMAGE \
  --ingress external --target-port 8000 \
  --min-replicas 1 --max-replicas 2 \
  --env-vars MARKETPLACE_MODE=mock DATABASE_PATH=/tmp/app.db
```

获取访问 URL：

```powershell
$FQDN = az containerapp show -g $RG -n $APP --query properties.configuration.ingress.fqdn -o tsv
"https://$FQDN/healthz"
"https://$FQDN/landing?token=demo-token"
```

### Live mode (calls Marketplace Fulfillment APIs)

### Live 模式（调用真实 Marketplace Fulfillment API）

> ⚠️ 注意：live 模式会调用真实 Marketplace Fulfillment API；请确保使用的是测试/沙箱配置（如适用），并妥善保管 `ENTRA_CLIENT_SECRET`（建议只用 ACA secret，不要明文落盘）。

通常建议把 client secret 存为 ACA **secret**。

环境变量说明：

- `ENTRA_TENANT_ID`：Entra 租户 ID（Directory/Tenant ID，GUID）
- `ENTRA_CLIENT_ID`：Entra 应用注册的 Client ID（Application/Client ID，GUID）
- `ENTRA_CLIENT_SECRET`：该应用的 Client Secret value（建议只以 ACA secret 形式保存，不要明文写入脚本/仓库）

```powershell
az containerapp secret set -g $RG -n $APP \
  --secrets entra-client-secret="<YOUR_SECRET>"

az containerapp update -g $RG -n $APP \
  --set-env-vars \
    MARKETPLACE_MODE=live \
    MARKETPLACE_API_BASE=https://marketplaceapi.microsoft.com \
    MARKETPLACE_API_VERSION=2018-08-31 \
    ENTRA_TENANT_ID="<YOUR_TENANT_ID>" \
    ENTRA_CLIENT_ID="<YOUR_CLIENT_ID>" \
    ENTRA_CLIENT_SECRET=secretref:entra-client-secret \
    DATABASE_PATH=/tmp/app.db
```

说明：
- Fulfillment 的 **Resolve** 调用需要通过请求头 `x-ms-marketplace-token` 传入购买 token（本服务内部会处理）。
- Landing page URL 中的 `token` query 参数就是 Marketplace 重定向带来的 purchase identification token。

## 6) View logs

## 6) 查看日志

```powershell
az containerapp logs show -g $RG -n $APP --follow
```

## 7) Update to a new image

## 7) 升级到新镜像版本

> 提示：`az containerapp update` 不会新建资源，但会触发拉取新镜像并滚动更新；运行与日志费用仍会持续。

```powershell
$IMAGE = "$ACR.azurecr.io/marketplace-saas-mvp:2"
cd ms-mkp-py-mvp

docker build -t $IMAGE .
docker push $IMAGE

az containerapp update -g $RG -n $APP --image $IMAGE
```

## 参考

- Landing page token + resolve: https://learn.microsoft.com/partner-center/marketplace-offers/azure-ad-transactable-saas-landing-page
- SaaS fulfillment subscription APIs v2: https://learn.microsoft.com/partner-center/marketplace-offers/pc-saas-fulfillment-subscription-api
