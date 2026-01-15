@echo off

%~d0
cd %~dp0
rmdir "pspdocmaker/__pycache__" /s /q
pyinstaller --onefile --noconsole --add-data "pspdocmaker;pspdocmaker" "pspdocmaker_gui.py"
del pspdocmaker_gui.spec
rmdir "build" /s /q
rmdir "pspdocmaker/__pycache__" /s /q

pause
