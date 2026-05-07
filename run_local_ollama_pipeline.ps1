$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not $env:AI_PROVIDER) { $env:AI_PROVIDER = "auto" }
if (-not $env:OLLAMA_MODEL) { $env:OLLAMA_MODEL = "qwen2.5:3b" }
if (-not $env:OLLAMA_BASE_URL) { $env:OLLAMA_BASE_URL = "http://localhost:11434" }
if (-not $env:PLAYWRIGHT_HEADLESS) { $env:PLAYWRIGHT_HEADLESS = "false" }

Write-Host "[INFO] Running local Ollama automation pipeline from $PSScriptRoot"
python run_pipeline.py
