; accessdr.nsi — NSIS installer script for AccessDR
;
; Build with:
;   "C:\Program Files (x86)\NSIS\makensis.exe" installer\accessdr.nsi
;
; Expects the PyInstaller output at dist\AccessDR\
; Produces: dist\installer\AccessDR-0.1.0-setup.exe

!include "MUI2.nsh"

; ---------------------------------------------------------------------------
; General
; ---------------------------------------------------------------------------
Name "AccessDR"
OutFile "..\dist\installer\AccessDR-0.1.0-setup.exe"
InstallDir "$LOCALAPPDATA\AccessDR"
InstallDirRegKey HKCU "Software\AccessDR" "InstallDir"
RequestExecutionLevel user
Unicode True

; ---------------------------------------------------------------------------
; Interface
; ---------------------------------------------------------------------------
!define MUI_ABORTWARNING
!define MUI_ICON "..\accessdr.ico"
!define MUI_UNICON "..\accessdr.ico"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\AccessDR.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Launch AccessDR"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ---------------------------------------------------------------------------
; Installer section
; ---------------------------------------------------------------------------
Section "AccessDR" SecMain
    SectionIn RO

    SetOutPath "$INSTDIR"
    File /r "..\dist\AccessDR\*.*"

    ; Store install dir in registry
    WriteRegStr HKCU "Software\AccessDR" "InstallDir" "$INSTDIR"

    ; Add/Remove Programs entry
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AccessDR" \
        "DisplayName" "AccessDR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AccessDR" \
        "DisplayVersion" "0.1.0"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AccessDR" \
        "Publisher" "AccessDR Contributors"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AccessDR" \
        "UninstallString" "$\"$INSTDIR\uninstall.exe$\""
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AccessDR" \
        "InstallLocation" "$INSTDIR"
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AccessDR" \
        "NoModify" 1
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AccessDR" \
        "NoRepair" 1

    ; Start menu shortcuts
    CreateDirectory "$SMPROGRAMS\AccessDR"
    CreateShortCut "$SMPROGRAMS\AccessDR\AccessDR.lnk" "$INSTDIR\AccessDR.exe"
    CreateShortCut "$SMPROGRAMS\AccessDR\Uninstall AccessDR.lnk" "$INSTDIR\uninstall.exe"

    ; Write uninstaller
    WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

; ---------------------------------------------------------------------------
; Optional desktop shortcut
; ---------------------------------------------------------------------------
Section "Desktop Shortcut" SecDesktop
    CreateShortCut "$DESKTOP\AccessDR.lnk" "$INSTDIR\AccessDR.exe"
SectionEnd

; ---------------------------------------------------------------------------
; Uninstaller
; ---------------------------------------------------------------------------
Section "Uninstall"
    ; Remove files
    RMDir /r "$INSTDIR"

    ; Remove Start menu shortcuts
    RMDir /r "$SMPROGRAMS\AccessDR"

    ; Remove desktop shortcut
    Delete "$DESKTOP\AccessDR.lnk"

    ; Remove registry keys
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AccessDR"
    DeleteRegKey HKCU "Software\AccessDR"
SectionEnd
