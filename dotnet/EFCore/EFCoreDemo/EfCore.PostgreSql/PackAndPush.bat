@ECHO OFF
SETLOCAL

:: Set paths
SET PROJECT_PATH=EfCore.PostgreSql.csproj
SET OUTPUT_DIR=bin\Release

:: Delete old .nupkg files
IF EXIST %OUTPUT_DIR%\*.nupkg (
    DEL /Q %OUTPUT_DIR%\*.nupkg
)

:: Pack project into Release directory
dotnet pack %PROJECT_PATH% -c Release -o %OUTPUT_DIR%
IF ERRORLEVEL 1 (
    ECHO [ERROR] Packing failed.
    GOTO END
)

:: Check if API key is set
IF "%NUGET_API_KEY%"=="" (
    ECHO [ERROR] NUGET_API_KEY environment variable is not set.
    GOTO END
)

:: Push all .nupkg files from bin\Release
FOR %%F IN (%OUTPUT_DIR%\*.nupkg) DO (
    ECHO Pushing %%F
    dotnet nuget push "%%F" -k %NUGET_API_KEY% -s https://api.nuget.org/v3/index.json --skip-duplicate
)

:END
PAUSE
ENDLOCAL
