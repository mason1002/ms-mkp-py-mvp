param(
  [Parameter(Mandatory=$true)]
  [string]$ResourceGroup,

  [Parameter(Mandatory=$true)]
  [string]$Location,

  [Parameter(Mandatory=$true)]
  [string]$AcrName,

  [Parameter(Mandatory=$true)]
  [string]$ContainerAppsEnvName,

  [Parameter(Mandatory=$true)]
  [string]$ContainerAppName,

  [Parameter(Mandatory=$false)]
  [string]$ImageTag = "1",

  [Parameter(Mandatory=$false)]
  [ValidateSet("mock","live")]
  [string]$MarketplaceMode = "mock",

  # Live mode only
  [Parameter(Mandatory=$false)]
  [string]$TenantId,

  [Parameter(Mandatory=$false)]
  [string]$ClientId,

  [Parameter(Mandatory=$false)]
  [string]$ClientSecret
)

$ErrorActionPreference = "Stop"

function Assert-Command($name) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    throw "Missing required command: $name"
  }
}

Assert-Command az
Assert-Command docker

Write-Host "Ensuring RG/ACR/ACA prerequisites..."
az group create -n $ResourceGroup -l $Location | Out-Null
az provider register "--namespace" Microsoft.App | Out-Null
az provider register "--namespace" Microsoft.OperationalInsights | Out-Null
az extension add "--name" containerapp "--upgrade" | Out-Null

$acr = az acr show -g $ResourceGroup -n $AcrName -o json 2>$null
if (-not $acr) {
  az acr create -g $ResourceGroup -n $AcrName "--sku" Basic | Out-Null
}

$acrLoginServer = az acr show -g $ResourceGroup -n $AcrName "--query" loginServer -o tsv
$fullImage = "$acrLoginServer/marketplace-saas-mvp:$ImageTag"

Write-Host "Logging into ACR and pushing image: $fullImage"
az acr login -n $AcrName | Out-Null

docker build -t $fullImage "$PSScriptRoot\.." 
docker push $fullImage

$env = az containerapp env show -g $ResourceGroup -n $ContainerAppsEnvName -o json 2>$null
if (-not $env) {
  Write-Host "Creating Container Apps environment: $ContainerAppsEnvName"
  az containerapp env create -g $ResourceGroup -n $ContainerAppsEnvName -l $Location | Out-Null
}

Write-Host "Creating/updating Container App: $ContainerAppName"

# Create if missing, otherwise update.
$app = az containerapp show -g $ResourceGroup -n $ContainerAppName -o json 2>$null

if (-not $app) {
  $createArgs = @(
    "containerapp", "create",
    "-g", $ResourceGroup,
    "-n", $ContainerAppName,
    "--environment", $ContainerAppsEnvName,
    "--image", $fullImage,
    "--ingress", "external",
    "--target-port", "8000",
    "--min-replicas", "1",
    "--max-replicas", "2",
    "--env-vars", "MARKETPLACE_MODE=$MarketplaceMode", "DATABASE_PATH=/tmp/app.db"
  )
  az @createArgs | Out-Null
} else {
  $updateImageArgs = @(
    "containerapp", "update",
    "-g", $ResourceGroup,
    "-n", $ContainerAppName,
    "--image", $fullImage
  )
  az @updateImageArgs | Out-Null
}

if ($MarketplaceMode -eq "live") {
  if (-not $TenantId -or -not $ClientId -or -not $ClientSecret) {
    throw "Live mode requires -TenantId, -ClientId, -ClientSecret"
  }

  $setSecretArgs = @(
    "containerapp", "secret", "set",
    "-g", $ResourceGroup,
    "-n", $ContainerAppName,
    "--secrets", "entra-client-secret=$ClientSecret"
  )
  az @setSecretArgs | Out-Null

  $setEnvArgs = @(
    "containerapp", "update",
    "-g", $ResourceGroup,
    "-n", $ContainerAppName,
    "--set-env-vars",
    "MARKETPLACE_MODE=live",
    "MARKETPLACE_API_BASE=https://marketplaceapi.microsoft.com",
    "MARKETPLACE_API_VERSION=2018-08-31",
    "ENTRA_TENANT_ID=$TenantId",
    "ENTRA_CLIENT_ID=$ClientId",
    "ENTRA_CLIENT_SECRET=secretref:entra-client-secret",
    "DATABASE_PATH=/tmp/app.db"
  )
  az @setEnvArgs | Out-Null
}

$fqdnArgs = @(
  "containerapp", "show",
  "-g", $ResourceGroup,
  "-n", $ContainerAppName,
  "--query", "properties.configuration.ingress.fqdn",
  "-o", "tsv"
)
$fqdn = az @fqdnArgs
Write-Host "Deployed. Test URLs:"
Write-Host "  https://$fqdn/healthz"
Write-Host "  https://$fqdn/landing?token=demo-token"
