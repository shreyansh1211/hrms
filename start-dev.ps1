# Starts everything Infisetu MIS needs locally: web server + background scheduler
# (auto sign-out after 12h, leave credits, payroll/work-record jobs).
Set-Location $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit","-Command","& .\.venv\Scripts\python.exe manage.py run_scheduler"
& .\.venv\Scripts\python.exe manage.py runserver 8000
