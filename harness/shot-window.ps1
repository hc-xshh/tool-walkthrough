# Capture a single top-level window to PNG (Windows).
#
#   powershell -File harness/shot-window.ps1 -Title "Agent" -Out runs/<run>/screens/S2.png
#   powershell -File harness/shot-window.ps1 -Hwnd 123456 -Out shot.png
#
# Full-screen capture (wt.py shot) shows whatever else is on the desktop;
# walkthrough evidence usually needs just the app window. Requires an
# interactive desktop session, same as wt.py shot.
param(
    [string]$Title = "",
    [int64]$Hwnd = 0,
    [string]$Out = ""
)

if (-not $Out) { Write-Error "usage: shot-window.ps1 -Title <substring>|-Hwnd <n> -Out <png>"; exit 2 }

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class WTWin {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder sb, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

  public static IntPtr FindByTitle(string needle) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => {
      if (!IsWindowVisible(h)) return true;
      var t = new StringBuilder(512); GetWindowText(h, t, 512);
      RECT r; GetWindowRect(h, out r);
      if (t.ToString().Contains(needle) && (r.Right - r.Left) > 200) { found = h; return false; }
      return true;
    }, IntPtr.Zero);
    return found;
  }
}
"@

if ($Hwnd -eq 0) {
    if (-not $Title) { Write-Error "need -Title or -Hwnd"; exit 2 }
    $Hwnd = [WTWin]::FindByTitle($Title).ToInt64()
    if ($Hwnd -eq 0) { Write-Error "no visible window whose title contains '$Title'"; exit 3 }
}

$h = [IntPtr]::new($Hwnd)
[WTWin]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 450

$r = New-Object WTWin+RECT
if (-not [WTWin]::GetWindowRect($h, [ref]$r)) { Write-Error "GetWindowRect failed"; exit 4 }
$w = $r.Right - $r.Left
$hgt = $r.Bottom - $r.Top
if ($w -le 0 -or $hgt -le 0) { Write-Error "window has no area ($w x $hgt)"; exit 5 }

$dir = Split-Path -Parent $Out
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
$bmp = New-Object System.Drawing.Bitmap $w, $hgt
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.Left, $r.Top, 0, 0, $bmp.Size)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "$Out ${w}x${hgt}"
