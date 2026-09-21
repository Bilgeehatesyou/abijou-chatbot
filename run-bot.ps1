# Keeps the bot (port 8000) and the ngrok tunnel running on this PC.
# Restarts the bot if it crashes. Logs: logs\bot.log
#   Start (hidden):  powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File D:\AjiltaiChatbot\run-bot.ps1
#   Stop:            .\stop-bot.ps1
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force logs | Out-Null
$log = Join-Path $PSScriptRoot "logs\bot.log"
$ngrokUrl = "https://state-tackling-drainpipe.ngrok-free.dev"

while ($true) {
    if (-not (Get-Process ngrok -ErrorAction SilentlyContinue)) {
        Add-Content $log "$(Get-Date -Format s) starting ngrok"
        Start-Process ngrok -ArgumentList "http", "8000", "--url", $ngrokUrl -WindowStyle Hidden
    }
    Add-Content $log "$(Get-Date -Format s) starting bot"
    # cmd does the redirect so the log stays plain UTF-8 (PowerShell 5.1 would write UTF-16)
    cmd /c "`"$PSScriptRoot\.venv\Scripts\python.exe`" -m uvicorn app.main:app --port 8000 >> `"$log`" 2>&1"
    Add-Content $log "$(Get-Date -Format s) bot stopped (exit $LASTEXITCODE), restarting in 5s"
    Start-Sleep -Seconds 5
}
