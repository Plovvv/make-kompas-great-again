"""Константы КОМПАС-3D, нужные модам. СГЕНЕРИРОВАНО `python tools/gen_constants.py`, вручную не править.

Источник: библиотеки типов Kompas6Constants (ksConstants.tlb) и Kompas6Constants3D (ksConstants3D.tlb)
из КОМПАС-3D v24. Это малая часть
всех констант КОМПАСа (отобрана группами в tools/gen_constants.py, с запасом). Имена совпадают с
именами в справке и примерах КОМПАСа, поэтому код читается рядом с документацией:

    from mkga.core import constants as C
    if doc_type == C.ksDocumentPart: ...

Не зависит от КОМПАСа и pywin32: работает в тестах и CI. Тест `tests/test_constants.py` сверяет
файл с библиотекой типов, когда КОМПАС установлен.
"""


# --- Типы документов (11) ---------------------------------------------
ksDocumentAssembly = 5
ksDocumentDrawing = 1
ksDocumentFragment = 2
ksDocumentLibraries = 21
ksDocumentLibrariesDirectories = 22
ksDocumentPart = 4
ksDocumentSheet = 0
ksDocumentSpecification = 3
ksDocumentTechnologyAssembly = 7
ksDocumentTextual = 6
ksDocumentUnknown = 0

# --- Спецификация: типы строк и варианты исполнения (15) --------------
ksSpecificationBaseObject = 1
ksSpecificationBilletObject = 7
ksSpecificationBlock = 4
ksSpecificationComment = 2
ksSpecificationCommonName = 8
ksSpecificationEmptyString = 6
ksSpecificationObjectCreateParam = 10128
ksSpecificationReserveString = 5
ksSpecificationSectionName = 3
ksSpecificationSimple = 0
ksSpecificationUnknownObject = 0
ksSpecificationVariantA = 1
ksSpecificationVariantB = 2
ksSpecificationVariantG = 4
ksSpecificationVariantV = 3

# --- Основная надпись: номера ячеек штампа (31) -----------------------
ksStApprovedBy = 115
ksStApprovedDate = 135
ksStAuthor = 110
ksStCheckedBy = 111
ksStCheckedDate = 131
ksStCompany = 9
ksStDescription = 2
ksStDesigner = 113
ksStDocumentCode = 52
ksStDocumentLetter1 = 40
ksStDocumentLetter2 = 41
ksStDocumentLetter3 = 42
ksStDocumentName = 51
ksStEndDesignDate = 130
ksStExecutionDate = 133
ksStFormat = 32
ksStFullFileName = 43
ksStMarkingLine = 45
ksStMass = 5
ksStMaterial = 3
ksStMfgApprovedBy = 112
ksStMfgApprovedDate = 132
ksStNumberOfSheets = 8
ksStOKPCode = 53
ksStPartNumber = 1
ksStRateOfInspection = 114
ksStRateOfInspectionDate = 134
ksStScale = 6
ksStSheetNumber = 7
ksStShortFileName = 44
ksStTypeOfWork = 10

# --- Типы объектов 3D-модели (ksObject*) (43) -------------------------
ksObjectAxis3D = 11188
ksObjectAxis3DBy2Planes = 11191
ksObjectAxis3DBy2Points = 11190
ksObjectAxis3DByConeface = 11192
ksObjectAxis3DByEdge = 11193
ksObjectAxis3DByOperation = 11195
ksObjectAxis3DByPointAndObject = 11194
ksObjectBody7 = 11009
ksObjectChamfer = 11257
ksObjectCutExtrusion = 11010
ksObjectCutRotated = 11129
ksObjectEvolution = 11276
ksObjectExtrusion = 11008
ksObjectFillet = 11259
ksObjectFullFillet = 11326
ksObjectLoft = 11271
ksObjectMassInertiaProperties = 10142
ksObjectMirrorPattern = 11093
ksObjectPlane3D = 11197
ksObjectPlane3DBy2Edge = 11209
ksObjectPlane3DBy3Points = 11201
ksObjectPlane3DByAngle = 11202
ksObjectPlane3DByEdgeAndPlane = 11208
ksObjectPlane3DByEdgeAndPoint = 11203
ksObjectPlane3DByOffset = 11200
ksObjectPlane3DByPlaneCurve = 11198
ksObjectPlane3DMiddle = 11207
ksObjectPlane3DNormalToSurface = 11206
ksObjectPlane3DParallelByPoint = 11204
ksObjectPlane3DPerpendicularByEdge = 11205
ksObjectPlane3DTangentToFace = 11210
ksObjectPlane3DTangentToFaceInPoint = 11199
ksObjectPlane3DUnhistoried = 11376
ksObjectPoint3D = 11014
ksObjectRotated = 11128
ksObjectSheetMetalBody = 11012
ksObjectShell = 11265
ksObjectSketch = 11006
ksObjectSketchs = 11005
ksObjectThread = 11242
ksObjectThreadPattern = 10118
ksObjectVariable7 = 10103
ksObjectVariableTable = 11004

# --- Типы объектов спецификации (ksObject*) (18) ----------------------
ksObjectSpecificationBaseObject = 10086
ksObjectSpecificationBaseObjects = 10083
ksObjectSpecificationColumn = 10089
ksObjectSpecificationColumnItem = 10091
ksObjectSpecificationColumnItems = 10090
ksObjectSpecificationColumns = 10088
ksObjectSpecificationCommentObject = 10087
ksObjectSpecificationCommentObjects = 10084
ksObjectSpecificationDescription = 10060
ksObjectSpecificationDescriptions = 10059
ksObjectSpecificationDocument = 10023
ksObjectSpecificationObject = 10085
ksObjectSpecificationSectionStyle = 10065
ksObjectSpecificationSectionStyles = 10064
ksObjectSpecificationStyle = 10061
ksObjectSpecificationStyles = 10522
ksObjectSpecificationSubsection = 10070
ksObjectSpecificationSubsections = 10069

# --- Типы операций построения 3D (pr*) (24) ---------------------------
prBaseEvolution = 20008
prBaseExtrusion = 20000
prBaseLoft = 20012
prBaseRotated = 20004
prBossEvolution = 20009
prBossExtrusion = 20001
prBossLoft = 20013
prBossRotated = 20005
prChamfer3D = 20017
prCutByPlane = 20018
prCutBySketch = 20019
prCutEvolution = 20010
prCutExtrusion = 20002
prCutLoft = 20014
prCutRotated = 20006
prEvolutionSurface = 20011
prExtrusionSurface = 20003
prFillet3D = 20016
prHole = 20032
prHoleConic = 20200
prHoleCounterbore = 20197
prHoleCounterdrill = 20199
prHoleCountersinking = 20198
prHoleSimple = 20196

# --- Единицы длины (ksLengthUnitsEnum) (4) ---------------------------
ksLUnDM = 2
ksLUnM = 3
ksLUnMM = 1
ksLUnSM = 0

# --- Размеры (ksDim*) (25) --------------------------------------------
ksDimACentre = 2
ksDimACentreLowFont = 0
ksDimALowerBoundary = 3
ksDimAUpperBoundary = 1
ksDimArrowAuto = 2
ksDimArrowInside = 0
ksDimArrowOutside = 1
ksDimBaseCenter = 0
ksDimBaseP1 = 1
ksDimBaseP2 = 2
ksDimBrackets = 1
ksDimBracketsOff = 0
ksDimCommonBase = 3
ksDimDeviation = 0
ksDimFirstCommonBase = 4
ksDimLimits = 1
ksDimLineLimits = 2
ksDimSquareBrackets = 2
ksDimTAuto = 0
ksDimTManual = 1
ksDimTextFormatGDD = 1
ksDimTextFormatGMS = 0
ksDimTextHorizontalInCut = 2
ksDimTextParallelInCut = 1
ksDimTextParallelOnLine = 0

# --- Исполнения КОМПАСа (ksKompas*): назначение значений ещё не проверено (15) ---
ksKompasConsumer = 4096
ksKompasDocument = 3
ksKompasExport = 101
ksKompasGraphic = 256
ksKompasHome = 1
ksKompasInvisible = 512
ksKompasLatin = 1024
ksKompasModule2D = 1
ksKompasModule3D = 2
ksKompasPrint = 100
ksKompasPro = 0
ksKompasSpds = 4
ksKompasStudy = 8192
ksKompasText = 4
ksKompasViewer = 2

# --- 3D: плоскости и оси детали по умолчанию (6) ---------------------
o3d_axisOX = 71
o3d_axisOY = 72
o3d_axisOZ = 73
o3d_planeXOY = 1
o3d_planeXOZ = 2
o3d_planeYOZ = 3

# --- 3D: типы объектов и операций (12) --------------------------------
o3d_baseExtrusion = 24
o3d_baseRotated = 27
o3d_bossExtrusion = 25
o3d_bossRotated = 28
o3d_cutBySketch = 51
o3d_cutExtrusion = 26
o3d_cutRotated = 29
o3d_edge = 7
o3d_face = 6
o3d_part = 104
o3d_sketch = 5
o3d_thread = 58

# --- 3D: направление выдавливания (ksDirectionTypeEnum) (4) ----------
dtBoth = 2
dtMiddlePlane = 3
dtNormal = 0
dtReverse = 1

# --- 3D: тип окончания выдавливания (ksEndTypeEnum) (7) --------------
etBlind = 0
etThroughAll = 1
etUpToNearSurface = 6
etUpToSurfaceFrom = 5
etUpToSurfaceTo = 4
etUpToVertexFrom = 3
etUpToVertexTo = 2

# --- 3D: тип вращения (ksRotatedTypeEnum) (3) ------------------------
ksRTAngle = 0
ksRTSurface = 2
ksRTVertex = 1

# Все константы одним словарём (для проверок и поиска по значению).
ALL = {
    "ksDocumentAssembly": ksDocumentAssembly,
    "ksDocumentDrawing": ksDocumentDrawing,
    "ksDocumentFragment": ksDocumentFragment,
    "ksDocumentLibraries": ksDocumentLibraries,
    "ksDocumentLibrariesDirectories": ksDocumentLibrariesDirectories,
    "ksDocumentPart": ksDocumentPart,
    "ksDocumentSheet": ksDocumentSheet,
    "ksDocumentSpecification": ksDocumentSpecification,
    "ksDocumentTechnologyAssembly": ksDocumentTechnologyAssembly,
    "ksDocumentTextual": ksDocumentTextual,
    "ksDocumentUnknown": ksDocumentUnknown,
    "ksSpecificationBaseObject": ksSpecificationBaseObject,
    "ksSpecificationBilletObject": ksSpecificationBilletObject,
    "ksSpecificationBlock": ksSpecificationBlock,
    "ksSpecificationComment": ksSpecificationComment,
    "ksSpecificationCommonName": ksSpecificationCommonName,
    "ksSpecificationEmptyString": ksSpecificationEmptyString,
    "ksSpecificationObjectCreateParam": ksSpecificationObjectCreateParam,
    "ksSpecificationReserveString": ksSpecificationReserveString,
    "ksSpecificationSectionName": ksSpecificationSectionName,
    "ksSpecificationSimple": ksSpecificationSimple,
    "ksSpecificationUnknownObject": ksSpecificationUnknownObject,
    "ksSpecificationVariantA": ksSpecificationVariantA,
    "ksSpecificationVariantB": ksSpecificationVariantB,
    "ksSpecificationVariantG": ksSpecificationVariantG,
    "ksSpecificationVariantV": ksSpecificationVariantV,
    "ksStApprovedBy": ksStApprovedBy,
    "ksStApprovedDate": ksStApprovedDate,
    "ksStAuthor": ksStAuthor,
    "ksStCheckedBy": ksStCheckedBy,
    "ksStCheckedDate": ksStCheckedDate,
    "ksStCompany": ksStCompany,
    "ksStDescription": ksStDescription,
    "ksStDesigner": ksStDesigner,
    "ksStDocumentCode": ksStDocumentCode,
    "ksStDocumentLetter1": ksStDocumentLetter1,
    "ksStDocumentLetter2": ksStDocumentLetter2,
    "ksStDocumentLetter3": ksStDocumentLetter3,
    "ksStDocumentName": ksStDocumentName,
    "ksStEndDesignDate": ksStEndDesignDate,
    "ksStExecutionDate": ksStExecutionDate,
    "ksStFormat": ksStFormat,
    "ksStFullFileName": ksStFullFileName,
    "ksStMarkingLine": ksStMarkingLine,
    "ksStMass": ksStMass,
    "ksStMaterial": ksStMaterial,
    "ksStMfgApprovedBy": ksStMfgApprovedBy,
    "ksStMfgApprovedDate": ksStMfgApprovedDate,
    "ksStNumberOfSheets": ksStNumberOfSheets,
    "ksStOKPCode": ksStOKPCode,
    "ksStPartNumber": ksStPartNumber,
    "ksStRateOfInspection": ksStRateOfInspection,
    "ksStRateOfInspectionDate": ksStRateOfInspectionDate,
    "ksStScale": ksStScale,
    "ksStSheetNumber": ksStSheetNumber,
    "ksStShortFileName": ksStShortFileName,
    "ksStTypeOfWork": ksStTypeOfWork,
    "ksObjectAxis3D": ksObjectAxis3D,
    "ksObjectAxis3DBy2Planes": ksObjectAxis3DBy2Planes,
    "ksObjectAxis3DBy2Points": ksObjectAxis3DBy2Points,
    "ksObjectAxis3DByConeface": ksObjectAxis3DByConeface,
    "ksObjectAxis3DByEdge": ksObjectAxis3DByEdge,
    "ksObjectAxis3DByOperation": ksObjectAxis3DByOperation,
    "ksObjectAxis3DByPointAndObject": ksObjectAxis3DByPointAndObject,
    "ksObjectBody7": ksObjectBody7,
    "ksObjectChamfer": ksObjectChamfer,
    "ksObjectCutExtrusion": ksObjectCutExtrusion,
    "ksObjectCutRotated": ksObjectCutRotated,
    "ksObjectEvolution": ksObjectEvolution,
    "ksObjectExtrusion": ksObjectExtrusion,
    "ksObjectFillet": ksObjectFillet,
    "ksObjectFullFillet": ksObjectFullFillet,
    "ksObjectLoft": ksObjectLoft,
    "ksObjectMassInertiaProperties": ksObjectMassInertiaProperties,
    "ksObjectMirrorPattern": ksObjectMirrorPattern,
    "ksObjectPlane3D": ksObjectPlane3D,
    "ksObjectPlane3DBy2Edge": ksObjectPlane3DBy2Edge,
    "ksObjectPlane3DBy3Points": ksObjectPlane3DBy3Points,
    "ksObjectPlane3DByAngle": ksObjectPlane3DByAngle,
    "ksObjectPlane3DByEdgeAndPlane": ksObjectPlane3DByEdgeAndPlane,
    "ksObjectPlane3DByEdgeAndPoint": ksObjectPlane3DByEdgeAndPoint,
    "ksObjectPlane3DByOffset": ksObjectPlane3DByOffset,
    "ksObjectPlane3DByPlaneCurve": ksObjectPlane3DByPlaneCurve,
    "ksObjectPlane3DMiddle": ksObjectPlane3DMiddle,
    "ksObjectPlane3DNormalToSurface": ksObjectPlane3DNormalToSurface,
    "ksObjectPlane3DParallelByPoint": ksObjectPlane3DParallelByPoint,
    "ksObjectPlane3DPerpendicularByEdge": ksObjectPlane3DPerpendicularByEdge,
    "ksObjectPlane3DTangentToFace": ksObjectPlane3DTangentToFace,
    "ksObjectPlane3DTangentToFaceInPoint": ksObjectPlane3DTangentToFaceInPoint,
    "ksObjectPlane3DUnhistoried": ksObjectPlane3DUnhistoried,
    "ksObjectPoint3D": ksObjectPoint3D,
    "ksObjectRotated": ksObjectRotated,
    "ksObjectSheetMetalBody": ksObjectSheetMetalBody,
    "ksObjectShell": ksObjectShell,
    "ksObjectSketch": ksObjectSketch,
    "ksObjectSketchs": ksObjectSketchs,
    "ksObjectThread": ksObjectThread,
    "ksObjectThreadPattern": ksObjectThreadPattern,
    "ksObjectVariable7": ksObjectVariable7,
    "ksObjectVariableTable": ksObjectVariableTable,
    "ksObjectSpecificationBaseObject": ksObjectSpecificationBaseObject,
    "ksObjectSpecificationBaseObjects": ksObjectSpecificationBaseObjects,
    "ksObjectSpecificationColumn": ksObjectSpecificationColumn,
    "ksObjectSpecificationColumnItem": ksObjectSpecificationColumnItem,
    "ksObjectSpecificationColumnItems": ksObjectSpecificationColumnItems,
    "ksObjectSpecificationColumns": ksObjectSpecificationColumns,
    "ksObjectSpecificationCommentObject": ksObjectSpecificationCommentObject,
    "ksObjectSpecificationCommentObjects": ksObjectSpecificationCommentObjects,
    "ksObjectSpecificationDescription": ksObjectSpecificationDescription,
    "ksObjectSpecificationDescriptions": ksObjectSpecificationDescriptions,
    "ksObjectSpecificationDocument": ksObjectSpecificationDocument,
    "ksObjectSpecificationObject": ksObjectSpecificationObject,
    "ksObjectSpecificationSectionStyle": ksObjectSpecificationSectionStyle,
    "ksObjectSpecificationSectionStyles": ksObjectSpecificationSectionStyles,
    "ksObjectSpecificationStyle": ksObjectSpecificationStyle,
    "ksObjectSpecificationStyles": ksObjectSpecificationStyles,
    "ksObjectSpecificationSubsection": ksObjectSpecificationSubsection,
    "ksObjectSpecificationSubsections": ksObjectSpecificationSubsections,
    "prBaseEvolution": prBaseEvolution,
    "prBaseExtrusion": prBaseExtrusion,
    "prBaseLoft": prBaseLoft,
    "prBaseRotated": prBaseRotated,
    "prBossEvolution": prBossEvolution,
    "prBossExtrusion": prBossExtrusion,
    "prBossLoft": prBossLoft,
    "prBossRotated": prBossRotated,
    "prChamfer3D": prChamfer3D,
    "prCutByPlane": prCutByPlane,
    "prCutBySketch": prCutBySketch,
    "prCutEvolution": prCutEvolution,
    "prCutExtrusion": prCutExtrusion,
    "prCutLoft": prCutLoft,
    "prCutRotated": prCutRotated,
    "prEvolutionSurface": prEvolutionSurface,
    "prExtrusionSurface": prExtrusionSurface,
    "prFillet3D": prFillet3D,
    "prHole": prHole,
    "prHoleConic": prHoleConic,
    "prHoleCounterbore": prHoleCounterbore,
    "prHoleCounterdrill": prHoleCounterdrill,
    "prHoleCountersinking": prHoleCountersinking,
    "prHoleSimple": prHoleSimple,
    "ksLUnDM": ksLUnDM,
    "ksLUnM": ksLUnM,
    "ksLUnMM": ksLUnMM,
    "ksLUnSM": ksLUnSM,
    "ksDimACentre": ksDimACentre,
    "ksDimACentreLowFont": ksDimACentreLowFont,
    "ksDimALowerBoundary": ksDimALowerBoundary,
    "ksDimAUpperBoundary": ksDimAUpperBoundary,
    "ksDimArrowAuto": ksDimArrowAuto,
    "ksDimArrowInside": ksDimArrowInside,
    "ksDimArrowOutside": ksDimArrowOutside,
    "ksDimBaseCenter": ksDimBaseCenter,
    "ksDimBaseP1": ksDimBaseP1,
    "ksDimBaseP2": ksDimBaseP2,
    "ksDimBrackets": ksDimBrackets,
    "ksDimBracketsOff": ksDimBracketsOff,
    "ksDimCommonBase": ksDimCommonBase,
    "ksDimDeviation": ksDimDeviation,
    "ksDimFirstCommonBase": ksDimFirstCommonBase,
    "ksDimLimits": ksDimLimits,
    "ksDimLineLimits": ksDimLineLimits,
    "ksDimSquareBrackets": ksDimSquareBrackets,
    "ksDimTAuto": ksDimTAuto,
    "ksDimTManual": ksDimTManual,
    "ksDimTextFormatGDD": ksDimTextFormatGDD,
    "ksDimTextFormatGMS": ksDimTextFormatGMS,
    "ksDimTextHorizontalInCut": ksDimTextHorizontalInCut,
    "ksDimTextParallelInCut": ksDimTextParallelInCut,
    "ksDimTextParallelOnLine": ksDimTextParallelOnLine,
    "ksKompasConsumer": ksKompasConsumer,
    "ksKompasDocument": ksKompasDocument,
    "ksKompasExport": ksKompasExport,
    "ksKompasGraphic": ksKompasGraphic,
    "ksKompasHome": ksKompasHome,
    "ksKompasInvisible": ksKompasInvisible,
    "ksKompasLatin": ksKompasLatin,
    "ksKompasModule2D": ksKompasModule2D,
    "ksKompasModule3D": ksKompasModule3D,
    "ksKompasPrint": ksKompasPrint,
    "ksKompasPro": ksKompasPro,
    "ksKompasSpds": ksKompasSpds,
    "ksKompasStudy": ksKompasStudy,
    "ksKompasText": ksKompasText,
    "ksKompasViewer": ksKompasViewer,
    "o3d_axisOX": o3d_axisOX,
    "o3d_axisOY": o3d_axisOY,
    "o3d_axisOZ": o3d_axisOZ,
    "o3d_planeXOY": o3d_planeXOY,
    "o3d_planeXOZ": o3d_planeXOZ,
    "o3d_planeYOZ": o3d_planeYOZ,
    "o3d_baseExtrusion": o3d_baseExtrusion,
    "o3d_baseRotated": o3d_baseRotated,
    "o3d_bossExtrusion": o3d_bossExtrusion,
    "o3d_bossRotated": o3d_bossRotated,
    "o3d_cutBySketch": o3d_cutBySketch,
    "o3d_cutExtrusion": o3d_cutExtrusion,
    "o3d_cutRotated": o3d_cutRotated,
    "o3d_edge": o3d_edge,
    "o3d_face": o3d_face,
    "o3d_part": o3d_part,
    "o3d_sketch": o3d_sketch,
    "o3d_thread": o3d_thread,
    "dtBoth": dtBoth,
    "dtMiddlePlane": dtMiddlePlane,
    "dtNormal": dtNormal,
    "dtReverse": dtReverse,
    "etBlind": etBlind,
    "etThroughAll": etThroughAll,
    "etUpToNearSurface": etUpToNearSurface,
    "etUpToSurfaceFrom": etUpToSurfaceFrom,
    "etUpToSurfaceTo": etUpToSurfaceTo,
    "etUpToVertexFrom": etUpToVertexFrom,
    "etUpToVertexTo": etUpToVertexTo,
    "ksRTAngle": ksRTAngle,
    "ksRTSurface": ksRTSurface,
    "ksRTVertex": ksRTVertex,
}
