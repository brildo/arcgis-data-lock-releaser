Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = currentDir & "\run.bat"

' 0 = vbHide (彻底隐藏控制台黑框)
ws.Run "cmd.exe /c """ & batPath & """", 0, False
