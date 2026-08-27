' Start Ratchet in the notification area, with no console window.
'
' Double-click this, or let the scheduled task created by
' ficsync\server\scripts\install_autostart.ps1 run it at login.
'
' A .vbs rather than a .bat because a batch file flashes a console window on
' the way to launching pythonw; this does not. For a visible console (when
' something is misbehaving and you want to watch it), use run.bat instead.

Option Explicit

Dim shell, fso, here, pythonw, serverDir
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

here = fso.GetParentFolderName(WScript.ScriptFullName)
serverDir = fso.BuildPath(here, "ficsync\server")
pythonw = fso.BuildPath(serverDir, ".venv\Scripts\pythonw.exe")

If Not fso.FileExists(pythonw) Then
    MsgBox "Ratchet's virtual environment is missing:" & vbCrLf & vbCrLf & _
           pythonw & vbCrLf & vbCrLf & _
           "Create it with:" & vbCrLf & _
           "  python -m venv .venv" & vbCrLf & _
           "  .venv\Scripts\python.exe -m pip install -r requirements.txt", _
           vbExclamation, "Ratchet"
    WScript.Quit 1
End If

' The service reads config.toml from the working directory.
shell.CurrentDirectory = serverDir
' 0 = hidden window, False = don't wait for it to finish.
shell.Run """" & pythonw & """ -m ficsync --tray", 0, False
