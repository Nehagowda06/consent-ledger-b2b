param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$UnittestArgs
)

$venvPython = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  Write-Error "Virtualenv Python not found at $venvPython"
  exit 1
}

if ($UnittestArgs -and $UnittestArgs.Count -gt 0) {
  & $venvPython -m unittest -v @UnittestArgs
} else {
  & $venvPython tests/run_security_suite.py
}
