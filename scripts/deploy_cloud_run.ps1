Param(
  [Parameter(Mandatory=$false)] [string]$ProjectId = $env:GOOGLE_CLOUD_PROJECT,
  [Parameter(Mandatory=$false)] [string]$Region = ${env:GOOGLE_CLOUD_REGION},
  [Parameter(Mandatory=$false)] [string]$ServiceName = "business-card-sync"
)

if (-not $ProjectId) { throw "Please provide -ProjectId or set GOOGLE_CLOUD_PROJECT" }
if (-not $Region) { $Region = "asia-east1" }

$ErrorActionPreference = 'Stop'

# Resolve repo root (script may be called from anywhere)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Resolve-Path (Join-Path $ScriptDir '..')
Set-Location $RepoRoot

Write-Host "Project = $ProjectId" -ForegroundColor Cyan
Write-Host "Region  = $Region" -ForegroundColor Cyan
Write-Host "Service = $ServiceName" -ForegroundColor Cyan

# Locate gcloud on Windows if PATH is missing
$gcloudCandidates = @(
  'gcloud',
  'gcloud.cmd',
  "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
  "$env:ProgramFiles\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
  "$env:ProgramFiles(x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
)
$GCLOUD = $null
foreach ($c in $gcloudCandidates) {
  if (Get-Command $c -ErrorAction SilentlyContinue) { $GCLOUD = $c; break }
  if (Test-Path $c) { $GCLOUD = $c; break }
}
if (-not $GCLOUD) { throw "gcloud not found. Please install Google Cloud SDK and re-run." }

# Build env var map from .env
$envPath = Join-Path $RepoRoot '.env'
if (-not (Test-Path $envPath)) { throw ".env not found at $envPath" }

$envMap = @{}
Get-Content $envPath | ForEach-Object {
  $line = $_.Trim()
  if ($line -eq '' -or $line.StartsWith('#')) { return }
  $parts = $line -split '=', 2
  if ($parts.Length -eq 2) {
    $key = $parts[0].Trim()
    $val = $parts[1].Trim()
    $envMap[$key] = $val
  }
}

# Ensure production-safe default
if (-not $envMap.ContainsKey('OAUTHLIB_INSECURE_TRANSPORT')) {
  $envMap['OAUTHLIB_INSECURE_TRANSPORT'] = '0'
}

# Write a temporary YAML file for --env-vars-file (handles special chars safely)
$tmpEnv = New-TemporaryFile
$yamlLines = @('---')
foreach ($k in $envMap.Keys) {
  $v = $envMap[$k].Replace("'", "''") # YAML single-quote escape
  $yamlLines += "${k}: '${v}'"
}
Set-Content -Path $tmpEnv -Value ($yamlLines -join "`n") -Encoding UTF8
Write-Host "Prepared env file: $tmpEnv" -ForegroundColor DarkGray

# Configure project
& $GCLOUD config set project $ProjectId | Out-Host

# Enable required services
& $GCLOUD services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com | Out-Host

# Build container image
$image = "gcr.io/${ProjectId}/${ServiceName}"
Write-Host "Building image $image ..." -ForegroundColor Yellow
& $GCLOUD builds submit --tag $image . | Out-Host

# Deploy Cloud Run service
Write-Host "Deploying Cloud Run service $ServiceName in $Region ..." -ForegroundColor Yellow
& $GCLOUD run deploy $ServiceName `
  --image $image `
  --platform managed `
  --region $Region `
  --allow-unauthenticated `
  --env-vars-file $tmpEnv `
  --port 8080 | Out-Host

# Print service URL
$url = (& $GCLOUD run services describe $ServiceName --platform managed --region $Region --format 'value(status.url)')
if ($url) {
  Write-Host "Service URL: $url" -ForegroundColor Green
  Write-Host "Add Google OAuth redirect URI: $url/auth/callback" -ForegroundColor Green
  Write-Host "Stripe webhook endpoint: $url/stripe/webhook" -ForegroundColor Green
}

Write-Host "Done." -ForegroundColor Cyan
