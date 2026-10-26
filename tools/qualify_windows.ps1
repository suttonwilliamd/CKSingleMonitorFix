# EPHEMERAL HOSTED WINDOWS RUNNER ONLY. Never run this on a user's host.
$ErrorActionPreference = 'Stop'
$rule = $null
New-Item -ItemType Directory -Force 'frozen-evidence' | Out-Null
# A fixed failure report exists even if setup/firewall enforcement stops the run.
'{"schema":1,"status":"fail","setup_failed":true,"cases":{}}' |
    Set-Content -Encoding utf8 'frozen-evidence/report.json'
try {
    if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or
        $env:RUNNER_OS -ne 'Windows') { throw 'Ephemeral hosted Windows required' }
    $exe = (Resolve-Path 'dist/CKSingleMonitorFix.exe').Path
    if ((Get-Service MpsSvc).Status -ne 'Running') { throw 'Firewall service unavailable' }
    $profiles = @(Get-NetFirewallProfile -PolicyStore ActiveStore)
    if ($profiles.Count -ne 3 -or @($profiles | Where-Object { -not $_.Enabled }).Count) {
        throw 'All firewall profiles must already be enabled'
    }
    $name = 'CK-frozen-' + [guid]::NewGuid().ToString('N')
    $rule = New-NetFirewallRule -Name $name -DisplayName $name -Direction Outbound `
        -Program $exe -Action Block -Profile Any -Enabled True
    $active = @(Get-NetFirewallRule -PolicyStore ActiveStore -Name $name)
    if ($active.Count -ne 1 -or $active[0].Enabled -ne 'True' -or
        $active[0].Action -ne 'Block' -or $active[0].Direction -ne 'Outbound' -or
        $active[0].Profile -ne 'Any') { throw 'Outbound deny not active' }
    $filters = @($active[0] | Get-NetFirewallApplicationFilter)
    if ($filters.Count -ne 1 -or $filters[0].Program -ne $exe) { throw 'Wrong program scope' }
    $source = (git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Source identity unavailable' }
    python tools/frozen_cli_smoke.py $exe --report frozen-evidence/report.json --source-sha $source
    if ($LASTEXITCODE -ne 0) { throw 'Synthetic qualification failed' }
} finally {
    if ($null -ne $rule) { $rule | Remove-NetFirewallRule }
}
