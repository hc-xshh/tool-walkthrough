param([Parameter(Mandatory = $true)][string]$Path)
$ErrorActionPreference = 'Stop'
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class QFolder {
  public delegate bool CB(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(CB cb, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string cls, string title);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr SendMessage(IntPtr h, uint msg, IntPtr w, string l);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern IntPtr GetDlgItem(IntPtr h, int id);
}
"@
$targetPid = (Get-Process 'Qoder CN' | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1).Id
$script:found = [IntPtr]::Zero
$cb = [QFolder+CB]{
    param($h, $l)
    if ([QFolder]::IsWindowVisible($h)) {
        $sb = New-Object System.Text.StringBuilder 256
        [void][QFolder]::GetClassName($h, $sb, 256)
        if ($sb.ToString() -eq '#32770') {
            $pid2 = 0
            [void][QFolder]::GetWindowThreadProcessId($h, [ref]$pid2)
            if ($pid2 -eq $targetPid) { $script:found = $h; return $false }
        }
    }
    return $true
}
$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline -and $script:found -eq [IntPtr]::Zero) {
    [void][QFolder]::EnumWindows($cb, [IntPtr]::Zero)
    if ($script:found -eq [IntPtr]::Zero) { Start-Sleep -Milliseconds 400 }
}
$dlg = $script:found
if ($dlg -eq [IntPtr]::Zero) { Write-Output 'dialog-not-found'; exit 2 }
$edit = [QFolder]::FindWindowEx($dlg, [IntPtr]::Zero, 'Edit', $null)
if ($edit -eq [IntPtr]::Zero) { Write-Output 'edit-not-found'; exit 3 }
[void][QFolder]::SendMessage($edit, 0x000C, [IntPtr]::Zero, $Path)
Start-Sleep -Milliseconds 500
$btn = [QFolder]::GetDlgItem($dlg, 1)
if ($btn -eq [IntPtr]::Zero) { Write-Output 'button-not-found'; exit 4 }
[void][QFolder]::SendMessage($btn, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)
Start-Sleep -Milliseconds 800
Write-Output "picked $Path"
exit 0