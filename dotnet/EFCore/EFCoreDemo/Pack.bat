@echo off
echo Packing NuGet package...
dotnet pack .\EfCore.PostgreSql\EfCore.PostgreSql.csproj -c Release
echo Done.
pause