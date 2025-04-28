@echo off

call pip install -r requirements.txt --no-warn-script-location
call python ./main.py

PAUSE
