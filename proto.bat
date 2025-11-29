@echo off
call conda activate chrono_310
cd /d "%~dp0prototype\sim_server"
python main.py
