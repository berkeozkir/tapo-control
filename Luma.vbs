Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
folder = fs.GetParentFolderName(WScript.ScriptFullName)
shell.Run Chr(34) & folder & "\.venv\Scripts\pythonw.exe" & Chr(34) & " " & Chr(34) & folder & "\tray_app.py" & Chr(34), 0, False
