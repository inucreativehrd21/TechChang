# PowerShell script to upload 2048 game files to Ubuntu server
# Run this from Windows PowerShell

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "2048 Game Files Upload Script" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# Configuration - UPDATE THESE VALUES
$serverUser = "your-username"  # Change this to your Ubuntu username
$serverIP = "your-server-ip"    # Change this to your Ubuntu server IP
$serverPath = "/home/$serverUser/projects/mysite"

Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Server User: $serverUser"
Write-Host "  Server IP: $serverIP"
Write-Host "  Server Path: $serverPath"
Write-Host ""

# Check if configuration needs to be updated
if ($serverUser -eq "your-username" -or $serverIP -eq "your-server-ip") {
    Write-Host "ERROR: Please update the configuration in this script!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Open this file in a text editor and change:" -ForegroundColor Yellow
    Write-Host '  $serverUser = "your-username"  # Change to your Ubuntu username' -ForegroundColor Yellow
    Write-Host '  $serverIP = "your-server-ip"    # Change to your Ubuntu server IP' -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Then run this script again." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# Files to upload
$files = @(
    @{
        local = "pybo\views\__init__.py"
        remote = "$serverPath/pybo/views/__init__.py"
        description = "Views package init (CRITICAL - imports game2048_views)"
    },
    @{
        local = "pybo\views\game2048_views.py"
        remote = "$serverPath/pybo/views/game2048_views.py"
        description = "2048 game logic and views"
    },
    @{
        local = "templates\pybo\game2048_play.html"
        remote = "$serverPath/templates/pybo/game2048_play.html"
        description = "2048 game template"
    },
    @{
        local = "fix_2048_404.sh"
        remote = "$serverPath/fix_2048_404.sh"
        description = "Automated fix script"
    },
    @{
        local = "verify_2048_files.sh"
        remote = "$serverPath/verify_2048_files.sh"
        description = "File verification script"
    }
)

# Check if files exist locally
Write-Host "Checking local files..." -ForegroundColor Yellow
$allFilesExist = $true

foreach ($file in $files) {
    if (Test-Path $file.local) {
        $size = (Get-Item $file.local).Length
        Write-Host "  [OK] $($file.local) ($size bytes)" -ForegroundColor Green
    } else {
        Write-Host "  [MISSING] $($file.local)" -ForegroundColor Red
        $allFilesExist = $false
    }
}

Write-Host ""

if (-not $allFilesExist) {
    Write-Host "ERROR: Some local files are missing!" -ForegroundColor Red
    Write-Host "Please ensure you're running this script from c:\projects\mysite\" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# Check if scp is available
$scpAvailable = $null -ne (Get-Command scp -ErrorAction SilentlyContinue)

if (-not $scpAvailable) {
    Write-Host "ERROR: scp command not found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "You need to install OpenSSH Client:" -ForegroundColor Yellow
    Write-Host "  1. Open Settings -> Apps -> Optional Features" -ForegroundColor Yellow
    Write-Host "  2. Click 'Add a feature'" -ForegroundColor Yellow
    Write-Host "  3. Find and install 'OpenSSH Client'" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Or use WinSCP/FileZilla to manually upload these files:" -ForegroundColor Yellow
    foreach ($file in $files) {
        Write-Host "  - $($file.local) -> $($file.remote)" -ForegroundColor Cyan
    }
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# Ask for confirmation
Write-Host "Ready to upload files to:" -ForegroundColor Yellow
Write-Host "  ${serverUser}@${serverIP}:${serverPath}" -ForegroundColor Cyan
Write-Host ""
$confirm = Read-Host "Continue? (yes/no)"

if ($confirm -ne "yes") {
    Write-Host "Upload cancelled." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "Uploading files..." -ForegroundColor Yellow
Write-Host ""

$uploadedCount = 0
$failedCount = 0

foreach ($file in $files) {
    Write-Host "Uploading $($file.local)..." -ForegroundColor Cyan
    Write-Host "  Description: $($file.description)" -ForegroundColor Gray

    # Upload file using scp
    $destination = "${serverUser}@${serverIP}:$($file.remote)"

    try {
        & scp $file.local $destination 2>&1 | Out-Null

        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [SUCCESS]" -ForegroundColor Green
            $uploadedCount++
        } else {
            Write-Host "  [FAILED] scp returned error code $LASTEXITCODE" -ForegroundColor Red
            $failedCount++
        }
    } catch {
        Write-Host "  [FAILED] $($_.Exception.Message)" -ForegroundColor Red
        $failedCount++
    }

    Write-Host ""
}

# Summary
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Upload Summary" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  Uploaded: $uploadedCount files" -ForegroundColor Green
Write-Host "  Failed: $failedCount files" -ForegroundColor $(if ($failedCount -gt 0) { "Red" } else { "Green" })
Write-Host ""

if ($failedCount -eq 0) {
    Write-Host "All files uploaded successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "  1. SSH into your server: ssh ${serverUser}@${serverIP}" -ForegroundColor Cyan
    Write-Host "  2. Go to project: cd ~/projects/mysite" -ForegroundColor Cyan
    Write-Host "  3. Make script executable: chmod +x fix_2048_404.sh" -ForegroundColor Cyan
    Write-Host "  4. Run the fix script: ./fix_2048_404.sh" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "The fix script will automatically:" -ForegroundColor Gray
    Write-Host "  - Verify all files" -ForegroundColor Gray
    Write-Host "  - Fix imports" -ForegroundColor Gray
    Write-Host "  - Clear cache" -ForegroundColor Gray
    Write-Host "  - Restart services" -ForegroundColor Gray
    Write-Host "  - Test the game" -ForegroundColor Gray
} else {
    Write-Host "Some files failed to upload!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Possible causes:" -ForegroundColor Yellow
    Write-Host "  - Incorrect server IP or username" -ForegroundColor Gray
    Write-Host "  - SSH authentication failed" -ForegroundColor Gray
    Write-Host "  - Network connection issues" -ForegroundColor Gray
    Write-Host "  - Server path doesn't exist" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Try:" -ForegroundColor Yellow
    Write-Host "  - Test SSH connection: ssh ${serverUser}@${serverIP}" -ForegroundColor Cyan
    Write-Host "  - Check server path exists: ssh ${serverUser}@${serverIP} 'ls -la ~/projects/mysite'" -ForegroundColor Cyan
}

Write-Host ""
Read-Host "Press Enter to exit"
