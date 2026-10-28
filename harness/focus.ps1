param([Parameter(Mandatory = $true)][string]$Name)
$ErrorActionPreference = 'Stop'
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinFocus {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
}
"@
$p = Get-Process | Where-Object { $_.ProcessName -like "*$Name*" -and $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { Write-Output 'no-window'; exit 3 }
if ([WinFocus]::IsIconic($p.MainWindowHandle)) { [void][WinFocus]::ShowWindow($p.MainWindowHandle, 9) }
[void][WinFocus]::ShowWindow($p.MainWindowHandle, 5)
[void][WinFocus]::SetForegroundWindow($p.MainWindowHandle)
Write-Output "$($p.ProcessName) $($p.Id)"