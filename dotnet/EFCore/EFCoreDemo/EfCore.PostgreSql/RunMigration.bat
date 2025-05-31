@ECHO OFF
SETLOCAL

:: Set your DbContext project folder (relative to this script)
SET PROJECT=EfCore.PostgreSql
SET CONTEXT=AppDbContext

:: Set the connection string here
SET CONNECTION_STRING=Host=localhost;Port=5432;Database=MyAppDb;Username=postgres;Password=123456;

:: Optional: Uncomment to create a new migration
:: SET MIGRATION_NAME=AddProductTable
:: dotnet ef migrations add %MIGRATION_NAME% --project %PROJECT% --context %CONTEXT%

:: Apply the latest migration to the database
dotnet ef database update --project %PROJECT% --context %CONTEXT% --connection "%CONNECTION_STRING%"

IF ERRORLEVEL 1 (
    ECHO [ERROR] Migration failed.
) ELSE (
    ECHO [SUCCESS] Database updated with latest migration.
)

PAUSE
ENDLOCAL