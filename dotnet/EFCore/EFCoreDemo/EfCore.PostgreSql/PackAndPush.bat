@echo off
echo Packing NuGet package...
del bin\Release\*.nupkg
dotnet pack .\EfCore.PostgreSql.csproj -c Release
dotnet nuget push bin\Release\EfCore.PostgreSql.*.nupkg --api-key %NUGET_API_KEY% --source https://api.nuget.org/v3/index.json
echo Done.
pause