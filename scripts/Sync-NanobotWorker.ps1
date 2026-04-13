# Copy nanobot-only artifacts to david@nanobot home (no sudo on client).
# After sync, SSH in once with TTY to install under /srv/chunkylink/repo and run Docker:
#
#   ssh -t david@nanobot 'sudo bash ~/chunkylink-nanobot-staging/install_nanobot_worker.sh'
#
# Or manually merge into /srv/chunkylink/repo and run deploy_nanobot_worker.sh.
#
# Usage:
#   .\scripts\Sync-NanobotWorker.ps1
#   .\scripts\Sync-NanobotWorker.ps1 -Target "david@nanobot.local"

param(
    [string] $Target = "david@nanobot"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $PSScriptRoot
$stage = "chunkylink-nanobot-staging"
$sshOpts = @("-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes")

Write-Host "Preparing $stage on $Target ..."
ssh @sshOpts $Target "rm -rf ~/$stage && mkdir -p ~/$stage/docker"

# rsync not always on Windows — use scp
$compose = Join-Path $here "docker\docker-compose.nanobot.yml"
$envEx = Join-Path $here ".env.nanobot.example"
$deploy = Join-Path $here "scripts\deploy_nanobot_worker.sh"
$install = Join-Path $here "scripts\install_nanobot_worker_from_home.sh"

scp @sshOpts $compose "${Target}:~/$stage/docker/docker-compose.nanobot.yml"
scp @sshOpts $envEx "${Target}:~/$stage/.env.nanobot.example"
scp @sshOpts $deploy "${Target}:~/$stage/deploy_nanobot_worker.sh"
scp @sshOpts $install "${Target}:~/$stage/install_nanobot_worker_from_home.sh"

Write-Host "Uploading worker/ (may take a minute) ..."
scp @sshOpts -r (Join-Path $here "worker") "${Target}:~/$stage/"

Write-Host ""
Write-Host "Sync complete. Finish on nanobot (sudo password once). Example for user david:"
Write-Host "  ssh -t $Target 'sudo bash /home/david/$stage/install_nanobot_worker_from_home.sh'"
Write-Host "Edit /srv/chunkylink/repo/.env.nanobot if the installer created it from the example."
Write-Host ""
