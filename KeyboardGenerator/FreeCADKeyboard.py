import math
from dataclasses import dataclass
from enum import Enum
from typing import List, final, Dict, Tuple
from itertools import groupby

from PySide2 import QtGui, QtCore, QtWidgets
import Part
import Draft
import FreeCAD
import Sketcher
import KeyboardQ
from Sketcher import Constraint

from KeyboardGenerator.KeyboardQ import KbIntermediaryData
from KeyboardQ import CornerStyle
import Key

class Orientation(str, Enum):
    AGNOSTIC = ''
    VERTICAL = 'Ver'
    HORIZONTAL = 'Hor'
        
@dataclass
class SketchAndExtrude():
    sketch: Sketcher.Sketch = None
    extrude: FreeCAD.DocumentObject = None

class KeyPoint():
    def __init__(self, id: int, keyNumber: int, baseKey: Key.BaseKey, extVertexId):
        self.id = id
        self.keyNumber = keyNumber
        key = baseKey.key
        biggestSize = baseKey.getBiggestSize()
        self.baseKey = baseKey

        if key.width > key.height:
            self.orientation = Orientation.HORIZONTAL
        elif key.height > key.width:
            self.orientation = Orientation.VERTICAL
        else:
            self.orientation = Orientation.AGNOSTIC

        self.size = biggestSize
        self.extVertexId = extVertexId

    def toU(self) -> str:        
        return self.baseKey.FloatToU(self.baseKey.getBiggestSize())
    
    def toIdStr(self) -> str:
        if self.size < self.baseKey.minStabSize: #2
            return self.baseKey.FloatToU(1)
        
        return self.toU() + self.orientation

    # Basically this method aims to create a FreeCAD document name friendly version of toLabelName()
    #
    # The name is unique per 'layout' that needs to be unique. Technically for
    # the default Cherry MX style rotating wouldn't be needed (a rotated square is still square)
    # but its easier to treat it the same as everything else rather than creating exceptions
    #
    # To figure out what is allowed in FreeCAD document names the FreeCAD wiki comes to the resue:
    # https://wiki.freecad.org/Object_name
    # The Name can only include simple alphanumeric characters, and the underscore, [_0-9a-zA-Z]
    # The Name cannot start with a number; it must start with a letter or the underscore, [_a-zA-Z]
    def toDocName(self, includeAngle: bool = False):
        docName = self.toLabelName(includeAngle)
        docName = docName.replace('.', '_')
        docName = docName.replace('°','deg')
        docName = docName.replace('↻', 'SwitchRotated')
        docName = docName.replace('⮃', 'StabFlipped')

        return docName

    # When adding new characters to this string make sure toDocName() reflects the same changes.
    def toLabelName(self, includeAngle: bool = False):
        fileNamePart = 'k1u'
        if self.baseKey.shouldBeStabilised():
            fileNamePart = f's{self.baseKey.getStabSizeU()}'
            fileNamePart += self.orientation

        if includeAngle and self.baseKey.key.rotation_angle != 0:
            fileNamePart += '{:g}°'.format(self.baseKey.key.rotation_angle)

        if self.baseKey.rotateSwitch:
            fileNamePart += '↻'

        if self.baseKey.flipped:
            fileNamePart += '⮃'
        
        return fileNamePart

@dataclass 
class IdAndLineSegment:
    id: int = 0
    lineSegment: Part.LineSegment = None

# FreeCAD.Vector is immutable, this class encapsulates it to add functionality.
# 
# To get around what I suspect are some slight deviations in numbers caused by
# rotation calculations rx() and ry() do some rounding to negate this.
class V:
    def __init__(self, vector: FreeCAD.Vector):
        self.vector = vector

    def rx(self):
        return round(self.vector.x, 10)

    def ry(self):
        return round(self.vector.y, 10)

    def isLeftOf(self, otherVector: 'V') -> bool:
        return self.rx() < otherVector.rx()

    def isAbove(self, otherVector: 'V') -> bool:
        return self.ry() < otherVector.ry()

    def isHorizontalTo(self, otherVector: 'V') -> bool:
        return self.ry() == otherVector.ry()

    def isVerticalTo(self, otherVector: 'V') -> bool:
        return self.rx() == otherVector.rx()

class VP(V):
    def __init__(self, vector: FreeCAD.Vector, id: int = 0):
        super().__init__(vector)
        self.id = id

# Convenience class for easily placing and constraining lines in a sketch
# It uses VP class (and thus V parent class) to round the numbers slightly 
# smoothing out minor inaccuracies caused by calculations.
class L():
    def __init__(self, line: Part.Line, id):
        self.line = line
        self.start = VP(line.StartPoint, 1) 
        self.end = VP(line.EndPoint, 2)
        self.id = id

    def isVertical(self) -> bool:
        return self.start.isVerticalTo(self.end)

    def isHorizontal(self) -> bool:
        return self.start.isHorizontalTo(self.end)
    
    def length(self) -> float:
        if self.isHorizontal():
            return abs(self.start.rx() - self.end.rx())
        else:
            return abs(self.start.ry() - self.end.ry())
        
    def getDistanceXConstraint(self) -> Constraint:
        if self.start.isLeftOf(self.end):
            return Constraint(
                'DistanceX', self.id, self.start.id, self.id, self.end.id, self.length()
            )
        
        #else self.end.isLeftOf(self.start):
        return Constraint(
            'DistanceX', self.id, self.end.id, self.id, self.start.id, self.length()
        )

    def getDistanceYConstraint(self) -> Constraint:
        if self.start.isAbove(self.end):
            return Constraint(
                'DistanceY', self.id, self.start.id, self.id, self.end.id, self.length()
            )
        elif self.end.isAbove(self.start):
            return Constraint(
                'DistanceY', self.id, self.end.id, self.id, self.start.id, self.length()
            )

    def getDirectionalConstraint(self) -> Constraint:
        if self.isHorizontal():
            return Constraint('Horizontal', self.id)
        
        return Constraint('Vertical', self.id)
    
    def getDistanceConstraint(self) -> Constraint:
        if self.isHorizontal():
            return self.getDistanceXConstraint()
        
        return self.getDistanceYConstraint()

    def getConstraints(self):
        constraints = []
        
        constraints.append(self.getDirectionalConstraint())
        constraints.append(self.getDistanceConstraint())

        return constraints
    
def toFv(self) -> FreeCAD.Vector():
    return FreeCAD.Vector(self.x(), self.y())
QtCore.QPointF.toFv = toFv

def checkLastConstraintRemoveIfRedundant(sketch: Sketcher.Sketch):
    if sketch.solve() == -2:
        sketch.delConstraint(len(sketch.Constraints)-1)
    
class KeyDocCollection():
    sketchPositions: Sketcher.Sketch = None
    sketchFootprint: Sketcher.Sketch = None
    extrusion: FreeCAD.Document = None
    pointArray: FreeCAD.DocumentObject = None
    keyPoint:  KeyPoint = None
    __prefix = ''

    def __init__(self, keyPoint: KeyPoint):
        self.keyPoint = keyPoint
        if keyPoint.baseKey.shouldBeStabilised():
            self.__prefix = 'Stab' + self.getIdStr()
        else: 
            self.__prefix = 'Key'

    # Convenience method equal to StabDocument.keyPoint.toIdStr()
    @final
    def getIdStr(self) -> str:
        return self.keyPoint.toIdStr()
        
    def getPositionsSketchName(self) -> str:
        return '{}PositionsSketch'.format(self.__prefix)
    
    def getFootPrintSketchName(self) -> str:
        return '{}Sketch'.format(self.__prefix)
    
    def getPointArrayName(self) -> str:
        return '{}PointArray'.format(self.__prefix)

class FreeCADKeyboard(KeyboardQ.KeyboardQ):
    switchesAndStabsToCut = []
    keyPoints: List[KeyPoint] = []
    keyboardStabPositionSketches = {}#: dict[str, Sketcher.Sketch] = {}

    # Qt uses the Cartesian coordinate system, FreeCAD does not adjust all.
    freecadTransform = QtGui.QTransform()
    freecadTransform.scale(1, -1)
    
    def createSketches(self, doc: FreeCAD.Document, body):
        self.doc = doc
        self.body = body

        self.sketch = self.doc.addObject('Sketcher::SketchObject', 'KeyboardPlateSketch')
        self.__sketchKeyboardCase()
        self.pad = self.__createPlatePad(self.sketch, self.thickness)

        self.doc.recompute() # KeyPosMasterSketch references self.sketch, recompute needed.
        self.__generateKeyPosMasterSketch()
        self.keyPoints = self.__addAndSortKeysAndStabs()
        self.__generateKeyAndStabSketches()  # Populates #self.keyAndStabBaseDocs
        self.__generateKeyAndStabExtrudes()
        self.doc.recompute() 
        self.__generateClonesAndPointArrays() # Clones and point array reference other files, recompute needed
        self.__generateFusion()
        self.__generateCut()

    # Any errors like:
    # kbStabPosSketch.addExternal(self.sketch.Name, keyPoint.extVertexId)
    #  ValueError: Not able to add external shape element
    # likely mean that vertexIdNumberOffset has been set incorrectly here.
    def __generateKeyPosMasterSketch(self):
        self.keyPosMasterSketch = self.doc.addObject('Sketcher::SketchObject', 'KeyPosMasterSketch')
        # First add external will be the id -3 by convention
        self.keyPosMasterSketch.addExternal(self.sketch.Name, 'Vertex2') # Top border, left Vertex
        topExternalPointId = -3

        # Second add external will be the id -4
        self.keyPosMasterSketch.addExternal(self.sketch.Name, 'Vertex3') # Left border, top vertex
        leftExternalPointId = -4

        # Create a point every key position will be constrained to, this is the most top left
        # point of the keyboard plate. If the top left corner is rounded/angled it will fall
        # outside the plate itself.
        self.anchorPointId = self.keyPosMasterSketch.addGeometry(Part.Point(FreeCAD.Vector()))
        anchorConstraints = [
            Constraint('Horizontal', topExternalPointId, 1, self.anchorPointId, 1),
            Constraint('Vertical', leftExternalPointId, 1, self.anchorPointId, 1),
        ]
        self.keyPosMasterSketch.addConstraint(anchorConstraints)

        # Other sketches will reference self.keyPosMasterSketch and need to know the external vertex id.
        # As there doesn't seem to a way to query the sketch directly to get the external id for a given
        # ID it seems like this needs to be tracked manually.
        self.vertexIdNumberOffset = 1

    def __addAndSortKeysAndStabs(self):
        keyReservedSpaceGis = self.getKeyReservedSpaceGis()
        # str = stabSize (or 1 for everything under the minimum stab size)
        keyPoints: Dict[str, List[KeyPoint]] = {}
        for index, keyReservedSpaceGi in enumerate(keyReservedSpaceGis):
            vertexId = f"Vertex{index + self.vertexIdNumberOffset}"
            keyPoint = self.__sketchKeyMidPoint(keyReservedSpaceGi, vertexId)
            self.addToKeyPointList(keyPoints, keyPoint)

        return keyPoints
    
    
    def __sketchKeyMidPoint(self, keyReservedSpace: KeyboardQ.KeyReservedSpaceGi, extVertexId: str) -> KeyPoint:
        bbox = keyReservedSpace.sceneBoundingRect()
        bbox = self.freecadTransform.mapRect(bbox)
        center: QtCore.QPointF = bbox.center()

        keyCenterPointId = self.keyPosMasterSketch.addGeometry(Part.Point(center.toFv()))
        self.keyPosMasterSketch.toggleConstruction(keyCenterPointId)
        self.keyPosMasterSketch.addConstraint(Constraint(
            'DistanceX', self.anchorPointId, 1, keyCenterPointId, 2, center.x()
        ))
        self.keyPosMasterSketch.addConstraint(Constraint(
            'DistanceY', self.anchorPointId, 2, keyCenterPointId, 1, center.y()
        ))
        
        keyPoint = KeyPoint(
            keyCenterPointId,
            keyCenterPointId,
            keyReservedSpace.data(0),
            extVertexId
        )
        self.keyPoints.append(keyPoint)

        return keyPoint
    
    
    def __generateKeyPositionSketch(self, idStr: str, keyPointList: List[KeyPoint]) -> Sketcher.Sketch:
        kbStabPosSketch = self.doc.addObject(
            'Sketcher::SketchObject', 
            idStr+"PositionsSketch"
        )

        for keyPoint in keyPointList:
            # If this line is throwing errors, check what the lowest ID of the most
            # bottom right Point in the first position sketch is (likely k1uPositionsSketch)
            #
            # The vertexIdNumberOffset variable in the __addAndSortKeysAndStabs() method should match that id.
            #
            # That's where this script creates the external vertex id hoping to reflect 
            # FreeCADs internal bookkeeping as I couldn't find any way to obtain it through the FreeCAD API.
            kbStabPosSketch.addExternal(self.keyPosMasterSketch.Name, keyPoint.extVertexId)
            extRefId = self.findIdForExternalGeometry(kbStabPosSketch, self.keyPosMasterSketch, keyPoint.extVertexId)
            stabPointId = kbStabPosSketch.addGeometry(Part.Point(FreeCAD.Vector(20, 20)))
            kbStabPosSketch.toggleConstruction(stabPointId)
            kbStabPosSketch.addConstraint(Constraint('Coincident', stabPointId, 1, extRefId, 1))

        return kbStabPosSketch
    
    # Big thanks to edwilliams16 on the FreeCAD forums
    # https://forum.freecad.org/viewtopic.php?t=76421#post_content663962
    def findIdForExternalGeometry(
        self, 
        sketch: Sketcher.Sketch, 
        targetSketch: Sketcher.Sketch, 
        targetName: str
    ) -> int:
        extGeometry: List[Tuple[Sketcher.Sketch, Tuple[str, ...]]]\
            = sketch.ExternalGeometry
        
        n = -3
        for sk, namelist in extGeometry:
            for name in namelist:
                if sk == targetSketch and name == targetName:
                    return n                
                n -= 1
        
        return None

    def __sketchKeyboardCase(self):
        def toLineSegment(self) -> Part.LineSegment:
            return Part.LineSegment(self.p1().toFv(), self.p2().toFv())
        QtCore.QLineF.toLineSegment = toLineSegment

        kbData = self.getKbIntermediaryData()

        borderIdAndLines: List[IdAndLineSegment] = []
        for border in kbData.getBorders():
            borderLine = border.toLineSegment()
            id = self.sketch.addGeometry(borderLine)
            borderIdAndLines.append(IdAndLineSegment(id, borderLine))
        self.keyboardTopLineId = borderIdAndLines[0].id
        self.keyboardLeftLineId = borderIdAndLines[1].id

        skipLastTwoDistanceConstraints = self.topRight.style == KeyboardQ.CornerStyle.RIGHT

        cornerLineIds = []
        for i, (corner, border) in enumerate(zip(KeyboardQ.Corner.Corners(), borderIdAndLines)):
            beforeLineId = border.id
            nextI = i+1 if i+1 < len(borderIdAndLines) else 0
            afterLineId = borderIdAndLines[nextI].id

            kbCorner: KeyboardQ.KbCorner = getattr(self, corner)
            if kbCorner.style == KeyboardQ.CornerStyle.ROUNDED:
                cornerLineIds.append(
                    self.addRoundedCorner(kbData, corner, beforeLineId, afterLineId)
                )
            elif kbCorner.style == KeyboardQ.CornerStyle.ANGLED:
                cornerLineIds.append(
                    self.addAngledCorner(kbData, corner, beforeLineId, afterLineId)
                )
            else: # No corner just constraint the borders
                self.sketch.addConstraint(Constraint('Coincident', beforeLineId, 2, afterLineId, 1))

            self.addLineConstraints(afterLineId, skipLastTwoDistanceConstraints and i >= 2)
            
    def addRoundedCorner(
        self, 
        kbData: KbIntermediaryData, 
        corner: KeyboardQ.Corner,
        beforeLineId: int,
        afterLineId: int,
    ):
        rect: QtCore.QRectF = kbData.getCornerRect(corner)
        halfWidth = rect.width()/2
        halfHeight = rect.height()/2
        lastCorner = corner == KeyboardQ.Corner.TOPRIGHT

        if rect.width() == rect.height():
            circle = Part.Circle(rect.center().toFv(), FreeCAD.Vector(0, 0, 1), halfWidth)
            cornerLineId = self.sketch.addGeometry(Part.ArcOfCircle(
                circle, kbData.getAngleAsRad(corner, 0), kbData.getAngleAsRad(corner, 90)
            ))
            # Circle self imposes constraints that are needed for the elipse
        elif rect.width() >= rect.height():
            ellipse = Part.Ellipse(rect.center().toFv(), halfWidth, halfHeight)
            cornerLineId = self.sketch.addGeometry(Part.ArcOfEllipse(
                ellipse, kbData.getAngleAsRad(corner, 0), kbData.getAngleAsRad(corner, 90)
            ))
            self.sketch.exposeInternalGeometry(cornerLineId)
            hLineId = cornerLineId+1
            vLineId = cornerLineId+2
            #if not lastCorner:
            self.sketch.addConstraint(Constraint('DistanceY', vLineId, 2, vLineId, 1, rect.height()))
            self.sketch.addConstraint(Constraint('Horizontal', hLineId))
        else:
            aRect = rect.transposed()
            ellipse = Part.Ellipse(rect.center().toFv(), halfWidth, halfHeight)
            ellipse.AngleXU = math.radians(90)
            cornerLineId = self.sketch.addGeometry(Part.ArcOfEllipse(
                ellipse, kbData.getAngleAsRad(corner, -90), kbData.getAngleAsRad(corner, 0)
            ))            
            self.sketch.exposeInternalGeometry(cornerLineId)            
            vLineId = cornerLineId+1
            hLineId = cornerLineId+2
            self.sketch.addConstraint(Constraint('DistanceY', vLineId, 2, vLineId, 1, aRect.width()))
            self.sketch.addConstraint(Constraint('Vertical', vLineId))

        self.sketch.addConstraint(Constraint('Coincident', beforeLineId, 2, cornerLineId, 1))
        self.sketch.addConstraint(Constraint('Coincident', afterLineId, 1, cornerLineId, 2))
        self.addArcConstraints(cornerLineId, lastCorner)
        

        return cornerLineId
        
    def addLineConstraints(self, lineId: int, skipDistance: bool = False):
        line: Part.LineSegment = self.sketch.Geometry[lineId]
        l = L(line, lineId)
        if skipDistance:
            self.sketch.addConstraint(l.getDirectionalConstraint())
        else:
            self.sketch.addConstraint(l.getConstraints())
        

    def addArcConstraints(self, geoId: int, lastCorner: bool):
        aoe: Part.ArcOfEllipse = self.sketch.Geometry[geoId]

        startOfArc = VP(aoe.StartPoint, 1)
        endOfArc = VP(aoe.EndPoint, 2)
        center = VP(aoe.Location, 3)

        constraints = []
        for arcPoint in [endOfArc, startOfArc]:
            if arcPoint.isHorizontalTo(center) and not lastCorner:
                constraints.append(Constraint(
                    'DistanceX', geoId, center.id, geoId, arcPoint.id, arcPoint.rx()-center.rx()
                ))
                constraints.append(Constraint('Horizontal', geoId, center.id, geoId, arcPoint.id))

            if arcPoint.isVerticalTo(center):
                constraints.append(Constraint('Vertical', geoId, center.id, geoId, arcPoint.id))

        self.sketch.addConstraint(constraints)

    def addAngledCorner(
        self,
        kbData: KbIntermediaryData,
        corner: KeyboardQ.Corner,
        beforeLineId: int,
        afterLineId: int,
    ):
        cornerLine = kbData.getCornerLine(corner)
        lineSegment = Part.LineSegment(cornerLine.p1().toFv(), cornerLine.p2().toFv())
        lineId = self.sketch.addGeometry(lineSegment)
        self.sketch.addConstraint(Constraint('Coincident', beforeLineId, 2, lineId, 1))
        self.sketch.addConstraint(Constraint('Coincident', afterLineId, 1, lineId, 2))
        
        rect: QtCore.QRectF = kbData.getCornerRect(corner)
        lastCorner = corner == KeyboardQ.Corner.TOPRIGHT
        cornerPoint = Part.Point(rect.center().toFv())
        cornerPointId = self.sketch.addGeometry(cornerPoint, True)

        cornerDistanceLine1 = Part.LineSegment(rect.center().toFv(), self.sketch.Geometry[beforeLineId].EndPoint)
        cornerDistanceLineId1 = self.sketch.addGeometry(cornerDistanceLine1, True)
        self.addLineConstraints(cornerDistanceLineId1, lastCorner)
        self.sketch.addConstraint(Constraint('Coincident', cornerPointId, 1, cornerDistanceLineId1, 1))
        self.sketch.addConstraint(Constraint('Coincident', beforeLineId, 2, cornerDistanceLineId1, 2))
        
        cornerDistanceLine2 = Part.LineSegment(rect.center().toFv(), self.sketch.Geometry[afterLineId].StartPoint)
        cornerDistanceLineId2 = self.sketch.addGeometry(cornerDistanceLine2, True)
        self.addLineConstraints(cornerDistanceLineId2, lastCorner)
        self.sketch.addConstraint(Constraint('Coincident', cornerPointId, 1, cornerDistanceLineId2, 1))
        self.sketch.addConstraint(Constraint('Coincident', afterLineId, 1, cornerDistanceLineId2, 2))

    def getKbIntermediaryData(self) -> KbIntermediaryData:
        roundedRect = super().getKbIntermediaryData()
        #self.freecadTransform.translate(roundedRect.difference.x(), roundedRect.difference.y())

        for key, value in roundedRect.__dict__.items():
            if hasattr(value, 'x') and hasattr(value, 'y'):
                setattr(roundedRect, key, self.freecadTransform.mapRect(value))
            elif hasattr(value, 'p1') and hasattr(value, 'p2'):
                setattr(roundedRect, key, QtCore.QLineF(self.freecadTransform.map(
                    value.p1()), self.freecadTransform.map(value.p2())))
        
        return roundedRect

    def __generateCut(self):
        self.cut = self.doc.addObject('Part::Cut', 'KbSwitchStabCutouts')
        self.cut.Base = self.kbPad
        self.cut.Tool = self.fusion
        #self.cut.ViewObject.ShapeColor = 
    
    # Fuse all keys and stabs together into one shape
    def __generateFusion(self):
        self.fusion = self.doc.addObject('Part::MultiFuse', 'KbPlateCutouts')
        self.fusion.Shapes = self.switchesAndStabsToCut

    def __generatePointArray(self, base: FreeCAD.DocumentObject, positionsSketch: Sketcher.Sketch):
        return Draft.make_point_array(base, positionsSketch)

    # Creates the base key / stabiliser sketches in a horizontal orientation.
    # This keeps the most complex step (the sketch) as at most one object centered in the sketch. 
    # All points where it's needed can clone this and mutate it as needed.
    #
    # This means sketches can have simple constraints as things aren't angled in the sketch itself.
    def __generateKeyAndStabSketches(self):

        #FileNamePart, Sketch
        keyAndStabBaseDocs: Dict[str, SketchAndExtrude] = {}

        for key, listOfKeyPoints in self.keyPoints.items():
            sketch = self.doc.addObject('Sketcher::SketchObject', key+'Sketch')
            firstEntry: Key.BaseKey = listOfKeyPoints[0].baseKey
            if firstEntry.shouldBeStabilised():
                for poly in firstEntry.getStabParts():
                    flippedPoly = self.freecadTransform.map(poly)
                    self.addQPolyToSketch(sketch,flippedPoly)
            else:
                self.addQPolyToSketch(sketch, firstEntry.footprint())
            keyAndStabBaseDocs[key] = SketchAndExtrude(sketch)

        self.keyAndStabBaseDocs = keyAndStabBaseDocs

    def __generateKeyAndStabExtrudes(self):
        for key, keyStabDoc in self.keyAndStabBaseDocs.items():
            extrude: FreeCAD.DocumentObject = self.createExtrusion(
                keyStabDoc.sketch, self.thickness
            )
            extrude.Visibility = False
            self.keyAndStabBaseDocs[key].extrude = extrude

    def __generateClonesAndPointArrays(self):
        # Flatten into a big list of keypoints
        flattenedSortedKeyPoints = (keyPoint for subList in self.keyPoints.values() for keyPoint in subList)

        # Group everything by angle (in addition to orientation and size and flipped stab)
        fullySortedKeyPoints: Dict[str, List[KeyPoint]] = {}
        for keyPoint in flattenedSortedKeyPoints:
            self.addToKeyPointList(fullySortedKeyPoints, keyPoint, True)

        for key, keyPointList in fullySortedKeyPoints.items():
            firstEntry: KeyPoint = keyPointList[0]
            labelNameWithoutRotation = firstEntry.toLabelName(False) 
            keyStabBaseDoc = self.keyAndStabBaseDocs[labelNameWithoutRotation]
            if len(keyPointList) > self.cloneCap:
                multiplyMe = None
                keyPositionSketch = self.__generateKeyPositionSketch(
                    firstEntry.toLabelName(True), keyPointList
                )
                if key == labelNameWithoutRotation:
                    multiplyMe = keyStabBaseDoc.extrude
                else:
                    clone = self.cloneAndRotate(keyStabBaseDoc.extrude, firstEntry)
                    clone.Label = f'{firstEntry.toLabelName(True)}'
                    multiplyMe = clone
                
                pa = self.__generatePointArray(multiplyMe, keyPositionSketch)
                pa.Label = f"{self.keyPointsToRangeString(keyPointList)} {key}PointArray"
                self.switchesAndStabsToCut.append(pa)
            else:
                for keyPoint in keyPointList:
                    clone = self.cloneAndMatchPositioning(keyStabBaseDoc.extrude, keyPoint)
                    self.switchesAndStabsToCut.append(clone)

    def addToKeyPointList(
        self,
        keyPoints: Dict[str, List[KeyPoint]],
        keyPoint: KeyPoint,
        incAngle: bool = False
    ):
        fileNamePart = keyPoint.toLabelName(incAngle)
        if fileNamePart not in keyPoints:
            keyPoints[fileNamePart] = []
        keyPoints[fileNamePart].append(keyPoint)

    def cloneAndMatchPositioning(self, doc: FreeCAD.DocumentObject, keyPoint: KeyPoint) -> Part.Part2DObject:
        clone = self.cloneAndRotate(doc, keyPoint)

        for (coordSmall, coordBig) in (('x', 'X'), ('y', 'Y')):
            clone.setExpression(
                f'.Placement.Base.{coordSmall}',
                f'{self.keyPosMasterSketch.Name}.Geometry[{keyPoint.id}].{coordBig}'
            )

        return clone
    
    def cloneAndRotate(self, doc: FreeCAD.DocumentObject, keyPoint: KeyPoint) -> Part.Part2DObject:
        clone: Part.Part2DObject = Draft.make_clone(doc)
        clone.Label = f'Key_{keyPoint.keyNumber} - {keyPoint.toLabelName(True)}'

        if keyPoint.baseKey.key.rotation_angle != 0:
            clone.Placement = FreeCAD.Placement(
                FreeCAD.Vector(),
                FreeCAD.Vector(),
                keyPoint.baseKey.key.rotation_angle * -1
            )

        return clone


    # Returns a string with the key numbers abbreviated, e.g. '1-4,5,6,9-10
    def keyPointsToRangeString(self, keyPointList: List[KeyPoint]) -> str:
        keyNumbers = [kp.keyNumber for kp in keyPointList]
        keyNumbers.sort()
        result = []
        for k, g in groupby(enumerate(keyNumbers), lambda i_x: i_x[0]-i_x[1]):
            seq = list(map(lambda i_x: i_x[1], g))
            if len(seq) > 1:
                result.append(f"{seq[0]}-{seq[-1]}")
            else:
                result.append(str(seq[0]))
        return ','.join(result)


    # Fills the given sketch with the given QPolygonF adding constraints where approperiate.
    # 
    # Note: Only does vertical/horizontal/distance/coincident constraints,
    # If the polygon contains any diagonals they won't be constrained.
    def addQPolyToSketch(self, sketch: Sketcher.Sketch, poly: QtGui.QPolygonF) -> Sketcher.Sketch:
        nFootPrintPoints = poly.length()
        firstLineId = None
        prevLineId = None
        qpointfList = poly.toList()

        # Start at 1 because 2 points are needed to draw a line [0, 1] [1, 2] etc
        r = range(1, nFootPrintPoints)
        for i in r:
            start = qpointfList[i-1].toTuple()
            end = qpointfList[i].toTuple()

            line = Part.LineSegment(FreeCAD.Vector(*start),FreeCAD.Vector(*end))
            lineId = sketch.addGeometry(line)
            l = L(line, lineId)
            constraints = l.getConstraints()

            if firstLineId == None:  # First loop
                firstLineId = lineId
                # Attach first point to center point of the sketch to eliminate degrees of freedom
                fX = round(qpointfList[0].x(), 8)
                fY = round(qpointfList[0].y(), 8) * -1
                constraints += [                    
                    Constraint('DistanceX', -1, 1, firstLineId, 1, fX),
                    Constraint('DistanceY', firstLineId, 1, -1, 1, fY)
                ]
            else:  # The loops in between the first and last one
                constraints.append(Constraint('Coincident', lineId, 1, prevLineId, 2))

            if i == nFootPrintPoints - 1:  # Last loop
                constraints = constraints[:-1] # Remove the last (redundant) constraint
                constraints.append(Constraint('Coincident', lineId, 2, firstLineId, 1))

            prevLineId = lineId
            sketch.addConstraint(constraints)

        return sketch
    
    def __createPlatePad(self, sketch: Sketcher.Sketch, thickness: float = 1.5):
        padName = sketch.Name.replace('Sketch', 'Pad')
        padLabel = sketch.Label.replace('Sketch', 'Pad')
        self.kbPad = self.body.newObject('PartDesign::Pad', padName)
        self.kbPad.Label = padLabel
        self.kbPad.Profile = self.sketch
        self.kbPad.Length = thickness        

    def createExtrusion(self, sketch: Sketcher.Sketch, thickness: float = 1.5):
        extrusionName = sketch.Name.replace('Sketch', 'Extrusion')
        extrusion = self.doc.addObject('Part::Extrusion', extrusionName)
        extrusion.Base = sketch
        extrusion.DirMode = 'Normal'
        extrusion.DirLink = None
        extrusion.LengthFwd = thickness
        extrusion.LengthRev = 0.0
        extrusion.Solid = True
        extrusion.Reversed = False
        extrusion.Symmetric = False
        extrusion.TaperAngle = 0.0
        extrusion.TaperAngleRev = 0.0

        extrusion.ViewObject.ShapeColor = getattr(
            sketch.getLinkedObject(True).ViewObject,
            'ShapeColor',
            extrusion.ViewObject.ShapeColor
        )
        extrusion.ViewObject.LineColor = getattr(
            sketch.getLinkedObject(True).ViewObject,
            'LineColor',
            extrusion.ViewObject.LineColor
        )
        extrusion.ViewObject.PointColor = getattr(
            sketch.getLinkedObject(True).ViewObject,
            'PointColor',
            extrusion.ViewObject.PointColor
        )
        sketch.Visibility = False

        return extrusion