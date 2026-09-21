# Copy the app to the server and restart it. Run from the project folder:
#   .\deploy\push.ps1 -Server root@1.2.3.4            # code only (keeps the server's database)
#   .\deploy\push.ps1 -Server root@1.2.3.4 -First     # first time: also .env, secrets/ and ajilt.db
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [switch]$First
)
$ErrorActionPreference = "Stop"
$tmp = Join-Path $env:TEMP "ajilt-deploy.tar.gz"

$items = @("app", "config", "data", "deploy", "requirements.txt")
if ($First) { $items += @(".env", "secrets", "ajilt.db") }
tar -czf $tmp --exclude="__pycache__" --exclude="*.pyc" @items

scp $tmp "${Server}:/tmp/ajilt-deploy.tar.gz"
Remove-Item $tmp

if ($First) {
    ssh $Server "mkdir -p /opt/ajilt && tar -xzf /tmp/ajilt-deploy.tar.gz -C /opt/ajilt && bash /opt/ajilt/deploy/server-setup.sh"
} else {
    ssh $Server "tar -xzf /tmp/ajilt-deploy.tar.gz -C /opt/ajilt && /opt/ajilt/.venv/bin/pip install --quiet -r /opt/ajilt/requirements.txt && chown -R ajilt:ajilt /opt/ajilt && systemctl restart ajilt && systemctl --no-pager status ajilt | head -5"
}
