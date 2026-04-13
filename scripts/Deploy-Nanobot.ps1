# Deploy ChunkyPotato pieces to nanobot (Ryzen Library worker + Ollama).
#
# Usage:
#   .\scripts\Deploy-Nanobot.ps1 -Sync                        # SCP worker bundle to ~/chunkylink-nanobot-staging, then run install (see below)
#   .\scripts\Deploy-Nanobot.ps1 -WorkerOnly                  # on-server: git pull + docker compose (needs sudo NOPASSWD or use -t manually)
#   .\scripts\Deploy-Nanobot.ps1                             # full deploy_chunkylink.sh + worker (only if nanobot also hosts the web app)
#   .\scripts\Deploy-Nanobot.ps1 -Target "david@nanobot.local"
#
# After -Sync, finish with an interactive SSH (sudo password once):
#   ssh -t david@nanobot 'sudo bash /home/david/chunkylink-nanobot-staging/install_nanobot_worker_from_home.sh'
#

param(
    [string] $Target = "david@nanobot",
    [switch] $WorkerOnly,
    [switch] $Sync
)

$sshOpts = @("-o", "StrictHostKeyChecking=accept-new")

if ($Sync) {
    & "$PSScriptRoot\Sync-NanobotWorker.ps1" -Target $Target
    Write-Host "Deploy-Nanobot: sync done. Run ssh -t with install command printed above."
    exit 0
}

if ($WorkerOnly) {
    Write-Host "Worker-only deploy on $Target (sudo required on server)..."
    Write-Host "If this fails with sudo: use ssh -t $Target 'sudo bash /srv/chunkylink/repo/scripts/deploy_nanobot_worker.sh'"
    $remote = "sudo bash /srv/chunkylink/repo/scripts/deploy_nanobot_worker.sh"
    Write-Host "SSH $Target -> $remote"
    ssh @sshOpts $Target $remote
} else {
    Write-Host "Full chunkylink deploy + worker on $Target"
    $remote = "sudo bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh"
    Write-Host "SSH $Target -> $remote"
    ssh @sshOpts $Target $remote

    Write-Host ""
    Write-Host "Rebuilding library worker containers..."
    $workerCmd = "sudo bash /srv/chunkylink/repo/scripts/deploy_nanobot_worker.sh"
    ssh @sshOpts $Target $workerCmd
}

Write-Host ""
Write-Host "Deploy complete."
