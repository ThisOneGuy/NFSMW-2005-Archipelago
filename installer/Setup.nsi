Unicode True
!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "FileFunc.nsh"
!include "StrFunc.nsh"
${StrRep}
Name "NFSMW Archipelago Client"
OutFile "${OUTPUT}/NFSMW_Setup.exe"
InstallDir "$PROGRAMFILES32\EA GAMES\Need for Speed Most Wanted"
InstallDirRegKey HKCU "Software\NFSMW Archipelago" "GameDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
VIProductVersion "1.0.5.0"
VIAddVersionKey "ProductName" "NFSMW Archipelago Client"
VIAddVersionKey "FileDescription" "NFSMW Client Setup"
VIAddVersionKey "FileVersion" "1.0.5"
VIAddVersionKey "ProductVersion" "1.0.5"
VIAddVersionKey "LegalCopyright" "NFSMW Archipelago contributors"
Icon "${ICON}"
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
Page custom GameDirectoryPage GameDirectoryLeave
Page custom ScriptPage ScriptLeave
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "English"
Var Dialog
Var CopyScripts
Var CopyCheck
Var GamePathEdit
Var LauncherInstalled
!include "InstallChecks.nsh"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "This client requires 64-bit Windows. NFSMW itself remains 32-bit."
    Abort
  ${EndIf}
  InitPluginsDir
  Call NormalizeGameDirectory
FunctionEnd
Function NormalizeGameDirectory
  ${StrRep} $INSTDIR $INSTDIR '"' ""
  ${StrRep} $INSTDIR $INSTDIR "/" "\"
TrimGameLeading:
  StrCpy $0 $INSTDIR 1
  StrCmp $0 " " 0 TrimGameTrailing
  StrCpy $INSTDIR $INSTDIR "" 1
  Goto TrimGameLeading
TrimGameTrailing:
  StrCpy $0 $INSTDIR 1 -1
  StrCmp $0 " " 0 NormalizeGameFull
  StrCpy $INSTDIR $INSTDIR -1
  Goto TrimGameTrailing
NormalizeGameFull:
  StrCmp $INSTDIR "" NormalizeGameDone
  GetFullPathName $INSTDIR "$INSTDIR"
  ${GetFileName} "$INSTDIR" $0
  ${If} $0 == "speed.exe"
    ${GetParent} "$INSTDIR" $INSTDIR
  ${EndIf}
TrimGameSlash:
  StrLen $0 $INSTDIR
  IntCmp $0 3 NormalizeGameDone NormalizeGameDone
  StrCpy $0 $INSTDIR 1 -1
  StrCmp $0 "\" 0 NormalizeGameDone
  StrCpy $INSTDIR $INSTDIR -1
  Goto TrimGameSlash
NormalizeGameDone:
FunctionEnd
Function GameDirectoryPage
  !insertmacro MUI_HEADER_TEXT "Choose Game Folder" "Select the existing folder containing speed.exe."
  nsDialogs::Create 1018
  Pop $Dialog
  ${NSD_CreateLabel} 0 0 100% 32u "Choose the NFSMW game folder. The client and required scripts install directly in the selected folder."
  Pop $0
  ${NSD_CreateDirRequest} 0 44u 80% 14u "$INSTDIR"
  Pop $GamePathEdit
  ${NSD_CreateBrowseButton} 82% 43u 18% 16u "Browse..."
  Pop $0
  ${NSD_OnClick} $0 BrowseGameDirectory
  nsDialogs::Show
FunctionEnd
Function BrowseGameDirectory
  Pop $0
  ${NSD_GetText} $GamePathEdit $INSTDIR
  Call NormalizeGameDirectory
  nsDialogs::SelectFolderDialog "Select the NFSMW folder containing speed.exe" "$INSTDIR"
  Pop $0
  ${If} $0 != "error"
    StrCpy $INSTDIR $0
    Call NormalizeGameDirectory
    ${NSD_SetText} $GamePathEdit "$INSTDIR"
  ${EndIf}
FunctionEnd
Function GameDirectoryLeave
  ${NSD_GetText} $GamePathEdit $INSTDIR
  Call NormalizeGameDirectory
  ${NSD_SetText} $GamePathEdit "$INSTDIR"
  StrCmp $INSTDIR "" 0 +3
    MessageBox MB_ICONSTOP "Choose the game folder containing speed.exe."
    Abort
  Push "$INSTDIR"
  Call NormalPath
  Pop $0
  ${If} $0 != 0
    Push "$INSTDIR\speed.exe"
    Call NormalPath
    Pop $0
  ${EndIf}
  ${If} $0 != 0
    Push "$INSTDIR\scripts"
    Call NormalTree
    Pop $0
  ${EndIf}
  ${If} $0 != 0
    Push "$INSTDIR\NFSMWClient_Data"
    Call NormalTree
    Pop $0
  ${EndIf}
  ${If} $0 != 0
    Push "$INSTDIR\client.exe"
    Call NormalPath
    Pop $0
  ${EndIf}
  ${If} $0 != 0
    Push "$INSTDIR\NFSMWClient.pyw"
    Call NormalPath
    Pop $0
  ${EndIf}
  ${If} $0 != 0
    Push "$INSTDIR\speed.exe"
    Call Pe32
    Pop $0
  ${EndIf}
  ${If} $0 == 0
    MessageBox MB_ICONSTOP "Select the game folder containing the 32-bit speed.exe. Linked script/data folders are not supported."
    Abort
  ${EndIf}
FunctionEnd
Function ScriptPage
  !insertmacro MUI_HEADER_TEXT "Game Scripts" "Close NFSMW and the connection client before updating."
  nsDialogs::Create 1018
  Pop $Dialog
  ${NSD_CreateCheckbox} 0 12u 100% 18u "Install the required game scripts and sounds"
  Pop $CopyCheck
  ${NSD_Check} $CopyCheck
  ${NSD_CreateLabel} 0 44u 100% 56u "Install the game plugin for version 1.0.5. Your saves and settings are kept. Only skip this step if the matching plugin is already installed."
  Pop $0
  nsDialogs::Show
FunctionEnd
Function ScriptLeave
  ${NSD_GetState} $CopyCheck $CopyScripts
  ${If} $CopyScripts != ${BST_CHECKED}
    Push "$INSTDIR\scripts\NFSMWArchipelago.asi"
    Call Pe32
    Pop $0
    ${If} $0 != 1
      MessageBox MB_ICONSTOP "Enable installation of the updated required game scripts."
      Abort
    ${EndIf}
  ${EndIf}
FunctionEnd
Section "Client"
  ClearErrors
  SetOutPath "$INSTDIR"
  File "${PAYLOAD}/NFSMWClient.pyw"
  SetOutPath "$INSTDIR\NFSMWClient_Data"
  File /r "${PAYLOAD}/NFSMWClient_Data/*"
  IfErrors InstallFailed
  ${If} $CopyScripts == ${BST_CHECKED}
    SetOutPath "$INSTDIR\scripts"
    File "${CORE}/NFSMWArchipelago.asi"
    File "${CORE}/NFSMWArchipelago.tpk"
    File "${CORE}/NFSMW_TurboTrap.wav"
    File "${CORE}/NFSMW_FlashBangTrap.wav"
    File "${CORE}/NFSMW_TruckTrap.wav"
    IfErrors InstallFailed
  ${EndIf}
  ClearErrors
  ExecWait '"$INSTDIR\NFSMWClient_Data\runtime\pythonw.exe" -I -S -B "$INSTDIR\NFSMWClient_Data\verify_install.pyw" "$INSTDIR\."' $0
  IfErrors InstallFailed
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "A required client or game-script file is missing, damaged or out of date. Enable installation of the required scripts and run Setup again. Details: NFSMWClient_Data\install_status.json"
    Abort
  ${EndIf}
  ClearErrors
  ExecWait '"$INSTDIR\NFSMWClient_Data\runtime\pythonw.exe" -I -S -B "$INSTDIR\NFSMWClient_Data\remove_retired.pyw" "$INSTDIR\."' $0
  IfErrors InstallFailed
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "Old mod files could not all be removed. Close the game and client, then run Setup again. Saves are preserved."
    Abort
  ${EndIf}
  WriteRegStr HKCU "Software\NFSMW Archipelago" "GameDir" "$INSTDIR"
  CreateDirectory "$SMPROGRAMS\NFSMW Archipelago"
  SetOutPath "$INSTDIR"
  ClearErrors
  StrCpy $LauncherInstalled 1
  SetOverwrite try
  File "${PAYLOAD}/client.exe"
  ${If} ${Errors}
    StrCpy $LauncherInstalled 0
  ${EndIf}
  SetOverwrite on
  ClearErrors
  CreateShortCut "$SMPROGRAMS\NFSMW Archipelago\NFSMW Client.lnk" "$INSTDIR\NFSMWClient_Data\runtime\pythonw.exe" '-I -S -B "$INSTDIR\NFSMWClient_Data\boot.pyw"' "$INSTDIR\NFSMWClient_Data\assets\archipelago.ico"
  IfErrors InstallFailed
  IfFileExists "$INSTDIR\client.exe" 0 LauncherUnavailable
  StrCmp $LauncherInstalled 1 InstallComplete
LauncherUnavailable:
  MessageBox MB_ICONINFORMATION "client.exe could not be installed or updated. Open NFSMW Client from the Start menu; it uses the bundled windowed runtime directly."
  Goto InstallComplete
InstallFailed:
  MessageBox MB_ICONSTOP "Some client files could not be installed. Close the client and game, check that the game folder is writable, then run Setup again. Existing saves are preserved."
  Abort
InstallComplete:
SectionEnd
