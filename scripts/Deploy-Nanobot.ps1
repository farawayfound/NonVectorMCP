# Run from your Windows dev machine after pushing to the remote Git repo.
# Requires OpenSSH client and passwordless or interactive sudo on the server.
#
# Usage:
#   .\scripts\Deploy-Nanobot.ps1
#   .\scripts\Deploy-Nanobot.ps1 -Target "david@nanobot.local"

param(
    [string] $Target = "david@nanobot"
)

$remote = "sudo bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh"
Write-Host "SSH $Target -> $remote"
# accept-new: first connect adds host key without interactive prompt
ssh -o StrictHostKeyChecking=accept-new $Target $remote
