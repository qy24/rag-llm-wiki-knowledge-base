# 运行全部后端测试（各测试模块设置独立环境，需分进程运行）
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
Set-Location (Join-Path $here '..\backend')
& .\.venv\Scripts\python.exe -m pytest tests\test_graph_persistence.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& .\.venv\Scripts\python.exe -m pytest tests\test_query_intent.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& .\.venv\Scripts\python.exe -m pytest tests\test_smoke.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& .\.venv\Scripts\python.exe -m pytest tests\test_vision.py -q -s
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& .\.venv\Scripts\python.exe -m pytest tests\test_live_server.py -q -s
exit $LASTEXITCODE
