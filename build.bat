@echo off

%~d0
cd %~dp0
rmdir "build" /s /q
rmdir "pspdocmaker/__pycache__" /s /q
pyinstaller --onefile --noconsole --add-data "pspdocmaker;pspdocmaker" "pspdocmaker_gui.py"
del pspdocmaker_gui.spec

del /f /q dist/pspdocmaker_gui.zip 2>nul
7z a -tzip pspdocmaker_gui.zip dist/pspdocmaker_gui.exe

pause
