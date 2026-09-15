Get-ChildItem -Recurse -Directory | ForEach-Object {
    # Controlla se la cartella è completamente vuota
    if (-not (Get-ChildItem -Path $_.FullName)) {
        $filePlaceholder = Join-Path $_.FullName "placeholder.txt"
        # Crea il file di testo vuoto
        New-Item -ItemType File -Force -Path $filePlaceholder | Out-Null
        Write-Host "Creato placeholder in: $($_.Name)" -ForegroundColor Cyan
    }
}
Write-Host "Fatto! Tutte le cartelle vuote ora hanno il loro placeholder." -ForegroundColor Green