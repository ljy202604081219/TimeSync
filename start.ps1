$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
# UTF-8 everywhere: project files, pip logs and uvicorn output are UTF-8 while a
# default Chinese Windows console still decodes with cp936/GBK.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
python -X utf8 run.py @args
