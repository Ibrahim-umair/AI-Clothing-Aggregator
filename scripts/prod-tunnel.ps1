<#
.SYNOPSIS
  Opens a local port forward into the production EC2 instance via AWS SSM
  Session Manager — no SSH, no open inbound port, matching how this project
  is administered everywhere else (see COMMANDS.md).

.DESCRIPTION
  The instance has no SSH key and its security group only allows 80/443 in.
  SSM Session Manager's port-forwarding feature tunnels a TCP port over the
  same IAM-authenticated channel used for shell access, so this is the SSH
  `-L` tunnel equivalent for an SSH-less box. Requires the AWS CLI, valid
  credentials for the account that owns the instance, and the Session
  Manager plugin (installed once via `winget install Amazon.SessionManagerPlugin`).

.EXAMPLE
  ./scripts/prod-tunnel.ps1 -Target grafana
  # then open http://localhost:3001  (user: admin / password: admin)

.EXAMPLE
  ./scripts/prod-tunnel.ps1 -Target db
  # then connect any Postgres client to localhost:5433
  # (db "libas", user "libas" — get the password via:
  #  aws ssm send-command --instance-ids <id> --document-name AWS-RunShellScript \
  #    --parameters 'commands=["docker exec libas-postgres env | grep POSTGRES_PASSWORD"]'
  #  then aws ssm get-command-invocation to read it back — never hardcode it here)
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("grafana", "db")]
    [string]$Target
)

$pluginDir = "C:\Program Files\Amazon\SessionManagerPlugin\bin"
if ((Test-Path $pluginDir) -and ($env:Path -notlike "*$pluginDir*")) {
    $env:Path += ";$pluginDir"
}

$InstanceId = "i-03771ac3d2f76e37d"

$ports = @{
    grafana = @{ Remote = 3001; Local = 3001; Note = "Grafana -> http://localhost:3001" }
    db      = @{ Remote = 5433; Local = 5433; Note = "Postgres -> localhost:5433 (db=libas, user=libas)" }
}
$p = $ports[$Target]

Write-Host "Tunneling $Target ($($p.Note)) -- Ctrl+C to close." -ForegroundColor Cyan

aws ssm start-session `
    --target $InstanceId `
    --document-name AWS-StartPortForwardingSession `
    --parameters "portNumber=$($p.Remote),localPortNumber=$($p.Local)"
