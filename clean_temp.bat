@echo off
REM Claude Code temporary files cleanup script (Windows)

echo Cleaning Claude temporary files...

set found=0

REM Check current directory
for %%f in (tmpclaude-*) do (
    if exist "%%f" (
        set found=1
    )
)

REM Check subdirectories recursively
for /r %%d in (tmpclaude-*) do (
    if exist "%%d" (
        set found=1
    )
)

if %found%==1 (
    echo Found temporary files, cleaning...

    REM Clean current directory
    del /q tmpclaude-* 2>nul
    rmdir /s /q tmpclaude-* 2>nul

    REM Clean subdirectories
    for /r %%d in (tmpclaude-*) do (
        if exist "%%d" (
            echo Removing: %%d
            if exist "%%d\*" (
                rmdir /s /q "%%d" 2>nul
            ) else (
                del /q "%%d" 2>nul
            )
        )
    )

    echo Cleaned temporary files
) else (
    echo No temporary files found
)

echo Done!
pause
