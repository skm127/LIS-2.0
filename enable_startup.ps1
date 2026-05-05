$sh = New-Object -ComObject WScript.Shell
$startupPath = [System.Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupPath "LIS.lnk"

Write-Host "Registering LIS for Windows Startup..."
$lnk = $sh.CreateShortcut($shortcutPath)
$lnk.TargetPath = Join-Path $PSScriptRoot "run_lis.bat"
$lnk.WorkingDirectory = $PSScriptRoot
$lnk.Description = "LIS - Sentient Digital Partner"
$lnk.Save()

Write-Host "Success! LIS will now greet you every time you log in to Windows."
