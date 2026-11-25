' Silent launcher for JCastBridge Tray App (zero console window)
Option Explicit

Dim WshShell, fso, strPath, pyExe

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strPath = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strPath

' Detect working Python (pythonw.exe or python.exe - both run hidden with window style 0)
If WshShell.Run("pythonw.exe -c ""exit(0)""", 0, True) = 0 Then
    pyExe = "pythonw.exe"
ElseIf WshShell.Run("python.exe -c ""exit(0)""", 0, True) = 0 Then
    pyExe = "python.exe"
ElseIf WshShell.Run("py.exe -c ""exit(0)""", 0, True) = 0 Then
    pyExe = "py.exe"
Else
    MsgBox "Python was not found in PATH." & vbCrLf & _
           "Please ensure Python 3.10+ is installed, or run JCastBridge.exe from dist\.", _
           vbCritical, "JCastBridge Launcher Error"
    WScript.Quit 1
End If

WshShell.Run pyExe & " """ & strPath & "\run_tray.py""", 0, False
