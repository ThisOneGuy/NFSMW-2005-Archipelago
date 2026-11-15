Function NormalPath
  Exch $0
  Push $1
  System::Call 'kernel32::GetFileAttributesW(w r0) i.r1'
  StrCmp $1 -1 NormalPathGood
  IntOp $1 $1 & 0x400
  StrCmp $1 0 NormalPathGood
  StrCpy $0 0
  Goto NormalPathDone
NormalPathGood:
  StrCpy $0 1
NormalPathDone:
  Pop $1
  Exch $0
FunctionEnd
Function NormalTree
  Exch $0
  Push $1
  Push $2
  Push $3
  StrCpy $3 1
  System::Call 'kernel32::GetFileAttributesW(w r0) i.r1'
  StrCmp $1 -1 NormalTreeDone
  IntOp $2 $1 & 0x400
  StrCmp $2 0 0 NormalTreeBad
  IntOp $2 $1 & 0x10
  StrCmp $2 0 NormalTreeDone
  ClearErrors
  FindFirst $1 $2 "$0\*"
NormalTreeNext:
  IfErrors NormalTreeClose
  StrCmp $2 "." NormalTreeFind
  StrCmp $2 ".." NormalTreeFind
  Push "$0\$2"
  Call NormalTree
  Pop $3
  StrCmp $3 0 NormalTreeClose
NormalTreeFind:
  ClearErrors
  FindNext $1 $2
  Goto NormalTreeNext
NormalTreeClose:
  FindClose $1
  Goto NormalTreeDone
NormalTreeBad:
  StrCpy $3 0
NormalTreeDone:
  StrCpy $0 $3
  Pop $3
  Pop $2
  Pop $1
  Exch $0
FunctionEnd
Function Pe32
  Exch $0
  Push $1
  Push $2
  Push $3
  Push $4
  ClearErrors
  FileOpen $1 "$0" r
  IfErrors Pe32Bad
  FileReadByte $1 $2
  StrCmp $2 77 0 Pe32CloseBad
  FileReadByte $1 $2
  StrCmp $2 90 0 Pe32CloseBad
  FileSeek $1 60 SET
  FileReadByte $1 $3
  FileReadByte $1 $2
  IntOp $2 $2 << 8
  IntOp $3 $3 | $2
  FileReadByte $1 $2
  IntOp $2 $2 << 16
  IntOp $3 $3 | $2
  FileReadByte $1 $2
  IntOp $2 $2 << 24
  IntOp $3 $3 | $2
  IfErrors Pe32CloseBad
  IntCmp $3 64 0 Pe32CloseBad
  FileSeek $1 0 END $4
  IntOp $4 $4 - 6
  IntCmp $3 $4 0 0 Pe32CloseBad
  FileSeek $1 $3 SET
  FileReadByte $1 $2
  StrCmp $2 80 0 Pe32CloseBad
  FileReadByte $1 $2
  StrCmp $2 69 0 Pe32CloseBad
  FileReadByte $1 $2
  StrCmp $2 0 0 Pe32CloseBad
  FileReadByte $1 $2
  StrCmp $2 0 0 Pe32CloseBad
  FileReadByte $1 $2
  StrCmp $2 76 0 Pe32CloseBad
  FileReadByte $1 $2
  StrCmp $2 1 0 Pe32CloseBad
  IfErrors Pe32CloseBad
  FileClose $1
  StrCpy $0 1
  Goto Pe32Done
Pe32CloseBad:
  FileClose $1
Pe32Bad:
  StrCpy $0 0
Pe32Done:
  Pop $4
  Pop $3
  Pop $2
  Pop $1
  Exch $0
FunctionEnd
