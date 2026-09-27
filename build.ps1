$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $compilerRoot = 'C:\msys64\ucrt64\bin'
    # windres/g++ spawn cc1.exe/as.exe as child processes, which dynamically
    # link libgmp/libmpfr/libisl/etc. from this folder. Without it on PATH,
    # those children fail to load and the parent tool exits 1 with no message.
    $env:PATH = "$compilerRoot;$env:PATH"
    $targetDirectory = Join-Path $PSScriptRoot 'dist\Luma'
    $targetExecutable = Join-Path $targetDirectory 'Luma.exe'
    $resourceObject = Join-Path $PSScriptRoot 'build\luma-resource.o'

    New-Item -ItemType Directory -Force -Path $targetDirectory, (Split-Path $resourceObject) | Out-Null

    Get-Process -Name Luma -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $targetExecutable } |
        Stop-Process -Force

    & "$compilerRoot\windres.exe" luma.rc -O coff -o $resourceObject
    if ($LASTEXITCODE -ne 0) { throw 'Luma icon resource build failed.' }

    & "$compilerRoot\g++.exe" -std=c++17 -O2 -municode -mwindows -static -static-libgcc -static-libstdc++ launcher.cpp $resourceObject -lshell32 -o $targetExecutable
    if ($LASTEXITCODE -ne 0) { throw 'Luma build failed.' }

    Write-Host "Built $targetExecutable"
} finally {
    Pop-Location
}
