# Stops the bot started by run-bot.ps1 (ngrok is left running).
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match 'run-bot\.ps1' -or $_.CommandLine -match 'uvicorn app\.main:app --port 8000' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
"bot stopped"
