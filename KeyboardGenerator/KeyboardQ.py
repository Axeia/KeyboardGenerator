# Inspired by kb.html from KLE
from typing import List, NamedTuple
from PySide2.QtGui import QPolygonF
from dataclasses import dataclass
from functools import cmp_to_key
from pykle_serial import serial
import typing
import xml.etree.ElementTree as ET
import math
from PySide2 import QtGui, QtCore
import FreeCAD
from enum import Enum
from PySide2.QtCore import QPointF as Qpf
from typing import List
from PySide2 import QtWidgets
import Key
import re


class Corner(str, Enum):
    NONE = 'none'
    TOPLEFT = 'topLeft'
    BOTTOMLEFT = 'bottomLeft'
    BOTTOMRIGHT = 'bottomRight'
    TOPRIGHT = 'topRight'

    # Returns all of the actual corners (Corner.NONE is not included)
    def Corners():
        return [x for x in Corner if x != 'none']
    
    # Expects wholeVarName to have a {} to be replaced with the corners name
    def ToVarName(self, wholeVarName: str = '') -> str:
        cornerAsVarName = self.value[0].upper() + self.value[1:]
        return wholeVarName.format(cornerAsVarName)
    
    def ToText(self) -> str:
        split = re.split(r'([A-Z][a-z]*)', self.value)
        split = [x.lower() for x in split]
        return ''.join(split).capitalize()
    
class Padding(str, Enum):
    NONE    = 'none'
    LEFT    = 'left'
    TOP     = 'top'
    RIGHT   = 'right'
    BOTTOM  = 'bottom'
    ALL     = 'all'

    def Sides():
        return [x for x in Padding if x not in [Padding.NONE, Padding.ALL]]

    def ToVarName(self, wholeVarName: str = '') -> str:
        if wholeVarName.__contains__('{}'):
            if wholeVarName.startswith('{}'):
                return wholeVarName.format(self.value)
            else:
                return wholeVarName.format(self.value.capitalize())
        
        return self.value

class KbShape(str, Enum):
    RECTANGULAR = 'Rectangular'
    CONVEX_HULL = 'Convex Hull'

class CornerStyle(Enum):
    ROUNDED = 1
    ANGLED = 2
    RIGHT = 3

@dataclass
class KbCorner():
    corner: Corner = Corner.NONE
    radiusX: float = 5.
    radiusY: float = 5.
    style: CornerStyle = CornerStyle.ROUNDED

    def getCornerRectSize(self) -> QtCore.QRectF():
        return QtCore.QSizeF(2*self.radiusX, 2*self.radiusY)

@dataclass
class UnitCountAndDifficulty:
    sizeInU:    str
    count:      int
    difficulty: Key.Difficulty

    def sizeAsFloat(self) -> float:
        return Key.CherryMx.StrToFloat(self.size)


@dataclass
class UnitDifficultyReport:
    unitCountAndDifficulties: typing.List[UnitCountAndDifficulty]
    totalCount:      int
    unsupportedSize: bool


@dataclass
class KeyAndStabDifficultyReports:
    keyReport: UnitDifficultyReport
    stabReport: UnitDifficultyReport

@dataclass
class KbIntermediaryData:
    leftBorder:             QtCore.QLineF
    bottomBorder:           QtCore.QLineF
    rightBorder:            QtCore.QLineF
    topBorder:              QtCore.QLineF
    topLeftRect:            QtCore.QRectF
    bottomLeftRect:         QtCore.QRectF
    bottomRightRect:        QtCore.QRectF
    topRightRect:           QtCore.QRectF
    bottomLeftCorner:       QtCore.QLineF
    bottomRightCorner:      QtCore.QLineF
    topRightCorner:         QtCore.QLineF
    topLeftCorner:          QtCore.QLineF
    bottomLeftStartAngle:   float = 180
    bottomRightStartAngle:  float = 270
    topRightStartAngle:     float = 0
    topLeftStartAngle:      float = 90

    def getCornerRect(self, corner: Corner) -> QtCore.QRectF:
        return getattr(self, corner.value+'Rect')
    
    def getArcBbox(self, corner: Corner) -> QtCore.QRectF:
        bigRect = self.getCornerRect(corner)
        partRect = QtCore.QRectF(bigRect.topLeft(), QtCore.QSizeF(
            bigRect.size().width()  / 2,
            bigRect.size().height() / 2
        ))

        offsetX = 0
        if corner == Corner.TOPRIGHT or corner == Corner.BOTTOMRIGHT:
            offsetX = partRect.width()
        offsetY = 0
        if corner == Corner.BOTTOMLEFT or corner == Corner.BOTTOMRIGHT:
            offsetY = partRect.height()

        partRect.translate(offsetX, offsetY)

        return partRect
    
    def getBorders(self):
        return [self.topBorder, self.leftBorder, self.bottomBorder, self.rightBorder]
    
    def getAngle(self, corner: Corner, additionalDegrees: float = 0.) -> float:
        return getattr(self, corner.value+'StartAngle') + additionalDegrees
    
    def getAngleAsRad(self, corner: Corner, additionalDegrees: float = 0.):
        return math.radians(self.getAngle(corner, additionalDegrees))
    
    def getCornerLine(self, corner: Corner) -> QtCore.QLineF:
        return getattr(self, corner.value+'Corner')


class PointsSVG():
    @classmethod
    def ToSvgPath(self, poly: QtGui.QPolygonF, pos: QtCore.QPointF) -> str:
        polygonString = ''
        for offset in poly.toList():
            destination = pos + offset
            polygonString += '{},{} '.format(
                round(destination.x(), 2),
                round(destination.y(), 2)
            )
        return polygonString.rstrip()

    @classmethod
    def GetPolySize(self, poly: QtGui.QPolygonF) -> QtCore.QSizeF():
        minX = maxX = minY = maxY = 0.0
        for point in poly.toList():
            minX = min(minX, point.x())
            maxX = max(maxX, point.x())
            minY = min(minY, point.y())
            maxY = max(maxY, point.y())
        return QtCore.QSizeF(maxX - minX, maxY - minY)

    @classmethod
    def PolygonToSvg(self, poly: QtGui.QPolygonF, clr: str = '#ffffff') -> bytearray:
        size = PointsSVG.GetPolySize(poly)

        root = self.GetSvgElement()
        root.set('width',  str(size.width()))
        root.set('height', str(size.height()))

        cutout = ET.SubElement(
            root, 'polygon',
            points=PointsSVG.ToSvgPath(
                poly,
                QtCore.QPointF(size.width() / 2, size.height() / 2)
            ),
            fill=clr,
        )

        return ET.tostring(root)

    @classmethod
    def PolygonsToSvg(self, clr='#ffffff', *polygons):
        size = QtCore.QSizeF(0, 0)

        for polygon in polygons:
            size += PointsSVG.GetPolySize(polygon)

        root = PointsSVG.GetSvgElement()
        root.set('width',  str(size.width()))
        root.set('height', '17')

        for polygon in polygons:
            cutout = ET.SubElement(
                root, 'polygon',
                points=PointsSVG.ToSvgPath(
                    polygon,
                    QtCore.QPointF(size.width() / 2, 17 / 2)
                ),
                fill=clr,
            )

        return ET.tostring(root)

    @classmethod
    def GetSvgElement(self):
        return ET.Element(
            'svg', version='1.1', xmlns='http://www.w3.org/2000/svg'
        )
    

class ContrastingSimpleTextGi(QtWidgets.QGraphicsSimpleTextItem):
    def paint(self, painter, option, widget):
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_Difference)
        painter.setOpacity(1)
        super().paint(painter, option, widget)

class KeyReservedSpaceGi(QtWidgets.QGraphicsRectItem):
    def __init__(self, rs: Key.KeyReservedSpace, hoverBrush: QtGui.QBrush, switchBrush: QtGui.QBrush):
        super().__init__(rs.reservedSpace)
        self.hoverBrush = hoverBrush
        self.switchBrush = switchBrush
        self.setData(0, rs)

        if rs.shouldBeStabilised():
            self.createStabilisedSwitch(rs, self)
            self.setCursor(QtCore.Qt.PointingHandCursor)
        else:
            switchGi = SwitchGi(rs.poly, self)
            switchGi.setPen(QtCore.Qt.NoPen)
            switchGi.setBrush(switchBrush)
        
        if rs.shouldBeStabilised() and rs.rotateSwitch:
            self.add180Icon()

        if rs.shouldBeStabilised() and rs.flipped:
            self.addFlippedIcons(rs)

    def add180Icon(self):
        txtRotateSwitch = ContrastingSimpleTextGi('↻', self)
        txtRotateSwitch.setBrush(QtCore.Qt.white)
        txtRotateSwitch.setPen(QtGui.QPen(QtGui.QBrush(QtCore.Qt.white), 0.1))
        txtRotateSwitch.setFont(QtGui.QFont("Segoe UI, Arial, sans-seriff", 4, QtGui.QFont.Normal))
        size = txtRotateSwitch.boundingRect().size()
        outerPos = self.pos()
        pos = QtCore.QPointF(
            outerPos.x() - (size.width() / 2),
            outerPos.y() - (size.height() / 2)
        )
        txtRotateSwitch.setPos(pos)

    def addFlippedIcons(self, rs: Key.KeyReservedSpace):
        stabFootprint = Key.Stabilizer.GetLeftFootPrint(rs.kerf, 0, rs.stabType)
        stabCenter = stabFootprint.boundingRect().center()
        txtFlippedLeft = self.addText('⮃', 2)
        leftSize = txtFlippedLeft.boundingRect().size()
        halfWidth = leftSize.width() / 2
        nubOffset = 0
        if rs.stabType in [Key.StabilizerType.CHERRY, Key.StabilizerType.CHERRY_COSTAR]:
            # These stabilizers have a nub on the side making the 'main body'  
            # center not actually appear centered, this compensates for that.
            nubOffset += 0.5 
        stabFootprintXOffset = stabCenter.x() + nubOffset

        #x = y, y = x. Things get flipped around here.
        if rs.isVertical():
            txtFlippedTop = txtFlippedLeft
            stabFootprintXOffset += rs.__class__.GetStabOffset(rs.key.height)
            stabFootPrintYOffset = stabCenter.y() + (leftSize.height() / 2)
            leftPos = QtCore.QPointF(stabFootPrintYOffset, -stabFootprintXOffset - halfWidth)
            txtFlippedTop.setRotation(90)
            txtFlippedTop.setPos(leftPos)

            txtFlippedBottom = self.addText('⮃', 2)
            rightPos = QtCore.QPointF(stabFootPrintYOffset, stabFootprintXOffset - halfWidth)
            txtFlippedBottom.setRotation(90)
            txtFlippedBottom.setPos(rightPos)
        else:
            stabFootprintXOffset += rs.__class__.GetStabOffset(rs.key.width)
            stabFootPrintYOffset = -stabCenter.y() - (leftSize.height() / 2)
            leftPos = QtCore.QPointF(-stabFootprintXOffset - halfWidth, stabFootPrintYOffset) 
            txtFlippedLeft.setPos(leftPos)

            txtFlippedRight = self.addText('⮃', 2)
            rightPos = QtCore.QPointF(stabFootprintXOffset - halfWidth, stabFootPrintYOffset)
            txtFlippedRight.setPos(rightPos)

    def addText(self, text: str, textSize: int) -> ContrastingSimpleTextGi:
        txtFlipped = ContrastingSimpleTextGi(text, self)
        txtFlipped.setBrush(QtCore.Qt.white)
        txtFlipped.setPen(QtGui.QPen(QtGui.QBrush(QtCore.Qt.white), 0.1))
        txtFlipped.setFont(QtGui.QFont("Segoe UI, Arial, sans-seriff", textSize, QtGui.QFont.Normal))

        return txtFlipped
    
    # Padding when doing a hullshape
    def Grow(self, growBy: float):
        center = self.boundingRect().center()
        newPolygon = QtGui.QPolygonF()

        for point in self.polygon():
            newPoint = point

            if point.x() < center.x():
                newPoint.setX(point.x() - growBy)
            else:
                newPoint.setX(point.x() + growBy)

            if point.y() < center.y():
                newPoint.setY(point.y() - growBy)
            else:
                newPoint.setY(point.y() + growBy)

            newPolygon.append(newPoint)

        polyGi = QtWidgets.QGraphicsPolygonItem(newPolygon)
        polyGi.setPos(self.pos())
        polyGi.setTransformOriginPoint(self.transformOriginPoint())
        polyGi.setTransform(self.transform())
        polyGi.setRotation(self.rotation())

        return polyGi

# data(0) = KeyReservedSpace
# data(1) = KeyboardQ
# data(2) = Elipse to highlight as origin point
    def hoverEnterEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        self.originalBrush = self.brush()
        self.setBrush(self.hoverBrush)
        data = self.data(2)
        if data:
            data.show()

    def hoverLeaveEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        data = self.data(2)
        self.setBrush(self.originalBrush)
        if data:
            data.hide()

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneHoverEvent) -> None:
        keyInfo: Key.KeyReservedSpace = self.data(0)
        if keyInfo.shouldBeStabilised():
            svbKbQ: KeyboardQ = self.data(1)
            if event.button() == QtCore.Qt.LeftButton:
                keyInfo.rotateSwitch = not keyInfo.rotateSwitch
            elif event.button() == QtCore.Qt.RightButton:
                keyInfo.flipped = not keyInfo.flipped

            svbKbQ.addKeyToScene(keyInfo)
            svbKbQ.scene.removeItem(self)
            originPointGi: QtWidgets.QGraphicsEllipseItem = self.data(2)
            if originPointGi:
                svbKbQ.scene.removeItem(originPointGi)

    def createStabilisedSwitch(
        self, keyInfo: Key.KeyReservedSpace, reservedSpace: QtWidgets.QGraphicsItem
    ) -> typing.List[QtWidgets.QGraphicsItem]:
        items = []
        for stabPart in keyInfo.getStabParts():
            polyGi = StabilisedSwitchGi(stabPart, reservedSpace)
            polyGi.setPen(QtCore.Qt.NoPen)
            polyGi.setBrush(self.switchBrush)
            items.append(polyGi)

        return items



# A key has 12 different locations that can have character on it.
#      +------------+
#     / 0   1   2  /| <- Top
#    / 3   4   5  / | <- Mid
#   / 6   7   8  /  | <- Bot
#  +------------+  /
#  | 9  10  11  | /   <- Side
#  +------------+/
#
class KeyLabelLocation(Enum):
    topLeft   = 0
    topMid    = 1
    topRight  = 2
    midLeft   = 3
    midMid    = 4
    midRight  = 5
    botLeft   = 6
    botMid    = 7
    botRight  = 8
    sideLeft  = 9
    sideMid   = 10
    sideRight = 11

    def IsOnSide(keyLabelLocation: 'KeyLabelLocation') -> bool:
        return keyLabelLocation in [
            KeyLabelLocation.sideLeft, 
            KeyLabelLocation.sideMid,
            KeyLabelLocation.sideRight
        ]

class KeyLabel():
    def __init__(self, labels: List):
        for i, label in enumerate(labels):
            setattr(self, KeyLabelLocation(i).name, label)

    def has(self, keyLabelLocation: KeyLabelLocation):
        return getattr(self, KeyLabelLocation(keyLabelLocation).name, None) is not None
    
    def get(self, keyLabelLocation: KeyLabelLocation):
        return getattr(self, KeyLabelLocation(keyLabelLocation).name)

class SwitchGi(QtWidgets.QGraphicsPolygonItem):
    pass
class StabilisedSwitchGi(SwitchGi):
    pass
        
class KbKeyGi(QtWidgets.QGraphicsRectItem):
    font = QtGui.QFont("Segoe UI, Arial, sans-seriff", 3, QtGui.QFont.Normal)
    edgeFont = QtGui.QFont("Segoe UI, Arial, sans-seriff", 2, QtGui.QFont.Normal)
    sideBrush: QtGui.QBrush = QtGui.QBrush(QtGui.QColor(204, 204, 204, 120))
    label: KeyLabel = None

    def __init__(self, __t, __obj, top: float, sides: float, bottom:  float, opacity: float):
        super().__init__(__t, __obj)
        self.topBorderWidth = top
        self.sideBorderWidth = sides
        self.bottomBorderWidth = bottom
        self.setOpacity(opacity)

    def setSideBrush(self, sideBrush: QtGui.QBrush):
        self.sideBrush = sideBrush

    def setLabels(self, labels: List):
        self.label = KeyLabel(labels)

        for keyLabelLocation in KeyLabelLocation:
            if self.label.has(keyLabelLocation):
                textGi = self.createSimpleTextItemChild(keyLabelLocation)

    def getTextPos(self, keyLabelLocation: KeyLabelLocation, textRect: QtCore.QRectF) -> QtCore.QPointF:
        extraPadding = 1
        fontHeight = self.font.pointSizeF()

        midX = (textRect.width()/2)*-1
        midY = (textRect.height()/2)*-1

        kcw = self.rect().width() - (2 * self.sideBorderWidth)
        left = extraPadding + (kcw/2)*-1
        right = (self.rect().width()/2) - self.sideBorderWidth - textRect.width() - extraPadding


        kch = self.rect().height() - self.topBorderWidth - self.bottomBorderWidth
        topY = extraPadding + self.topBorderWidth + (((kch/2) + fontHeight)*-1)
        botY = (kch/2) - textRect.height() - extraPadding

        botSide = botY + self.bottomBorderWidth

        if keyLabelLocation == KeyLabelLocation.topLeft:
            return QtCore.QPointF(left, topY)
        elif keyLabelLocation == KeyLabelLocation.topMid:
            return QtCore.QPointF(midX, topY)
        elif keyLabelLocation == KeyLabelLocation.topRight:
            return QtCore.QPointF(right, topY)
        elif keyLabelLocation == KeyLabelLocation.midLeft:
            return QtCore.QPointF(left, midY)
        elif keyLabelLocation == KeyLabelLocation.midMid:
            return QtCore.QPointF(midX, midY)
        elif keyLabelLocation == KeyLabelLocation.midRight:
            return QtCore.QPointF(right, midY)
        elif keyLabelLocation == KeyLabelLocation.botLeft:
            return QtCore.QPointF(left, botY)
        elif keyLabelLocation == KeyLabelLocation.botMid:
            return QtCore.QPointF(midX, botY)
        elif keyLabelLocation == KeyLabelLocation.botRight:
            return QtCore.QPointF(right, botY)
        elif keyLabelLocation == KeyLabelLocation.sideLeft:
            return QtCore.QPointF(left,botSide)
        elif keyLabelLocation == KeyLabelLocation.sideMid:
            return QtCore.QPointF(midX, botSide)
        elif keyLabelLocation == KeyLabelLocation.sideRight:
            return QtCore.QPointF(right, botSide)

    def createSimpleTextItemChild(self, keyLabelLocation: KeyLabelLocation) -> QtWidgets.QGraphicsSimpleTextItem:
        text = re.sub('''<\s*br\/?\s*>''', '\n', self.label.get(keyLabelLocation))
        textGi = ContrastingSimpleTextGi(text, self)
        textGi.setBrush(QtGui.QBrush(QtGui.QColor(255, 255, 255, 255)))
        textGi.setPen(QtGui.QPen(QtGui.QBrush(QtCore.Qt.transparent), 0))
        if KeyLabelLocation.IsOnSide(keyLabelLocation):
            textGi.setFont(KbKeyGi.edgeFont)
        else:
            textGi.setFont(KbKeyGi.font)

        textGi.setPos(self.getTextPos(keyLabelLocation, textGi.boundingRect()))

        return textGi

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionGraphicsItem, widget: QtWidgets.QWidget):
        rect = self.rect()

        keyFaceRect = QtCore.QRectF(
            rect.x() + self.sideBorderWidth,
            rect.y() + self.topBorderWidth,
            rect.width() - (2 * self.sideBorderWidth),
            rect.height() - self.topBorderWidth - self.bottomBorderWidth
        )
        
        keyCapSidePath = QtGui.QPainterPath()
        keyCapSidePath.addRoundedRect(rect, 2, 2)

        keyCapTopPath = QtGui.QPainterPath()
        keyCapTopPath.addRoundedRect(keyFaceRect, 2, 2)
        
        painter.setPen(self.pen())
        painter.setBrush(self.sideBrush)
        painter.drawPath(keyCapSidePath)

        painter.setBrush(self.brush())
        painter.drawPath(keyCapTopPath)

class ArrowLine(QtWidgets.QGraphicsLineItem):
    font = QtGui.QFont("Consolas, DejaVu Sans Mono, monospace", 5, QtGui.QFont.Normal)

    def __init__(self, *args: tuple) -> None:
        super().__init__(*args)

        label = "{}ᴍᴍ".format(round(self.line().length(), 3))        
        self.textGi = ContrastingSimpleTextGi(label, self)
        #self.textGi.setBrush() - Done externally
        self.textGi.setPen(QtGui.QPen(QtGui.QBrush(QtCore.Qt.transparent), 0))
        self.textGi.setFont(ArrowLine.font)
        bbox = self.textGi.boundingRect()

        posOffset = QtCore.QPointF()
        if self.isVertical():
            self.textGi.setRotation(-90)
            posOffset = QtCore.QPointF(bbox.height()*-0.5, bbox.width()*0.5)
            self.textGi.setToolTip(label + " high")
        else:
            posOffset = QtCore.QPointF(bbox.width()*-0.5, bbox.height()*-0.5)
            self.textGi.setToolTip(label + " wide")
        self.textGi.setPos(self.line().center() + posOffset)

    def isVertical(self):
        return self.line().dy() != 0

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionGraphicsItem, widget: QtWidgets.QWidget) -> None:
        painter.setPen(self.pen())
        startArrowWing1, startArrowWing2, endArrowWing1, endArrowWing2 = self.getArrowLines()
        bbox = self.textGi.boundingRect()
        if self.isVertical():
            # Why bother with expensive rotate calculations, this will do
            bbox = bbox.transposed()
        bbox.moveCenter(self.line().center())

        if self.isVertical():
            painter.drawLine(self.line().p1(), QtCore.QPointF(self.line().p1().x(), bbox.bottom()+1))
            painter.drawLine(QtCore.QPointF(self.line().p2().x(), bbox.top()-1), self.line().p2())      
        else:
            painter.drawLine(self.line().p1(), QtCore.QPointF(bbox.left()-1, self.line().p1().y()))
            painter.drawLine(QtCore.QPointF(bbox.right()+1, self.line().p2().y()), self.line().p2())
        
        painter.drawLine(startArrowWing1)
        painter.drawLine(startArrowWing2)
        painter.drawLine(endArrowWing1)
        painter.drawLine(endArrowWing2)

    def getArrowLines(self) -> typing.List[QtCore.QLineF]:
        startArrowWing1 = self.line()
        startArrowWing1.setAngle(self.line().angle()+35)
        startArrowWing1.setLength(4)
        startArrowWing1.setP1(self.line().p1())

        startArrowWing2 = self.line()
        startArrowWing2.setAngle(self.line().angle()-35)
        startArrowWing2.setLength(4)
        startArrowWing2.setP1(self.line().p1())

        endArrowWing1 = QtCore.QLineF()
        endArrowWing1.setP1(self.line().p2())
        endArrowWing1.setAngle(self.line().angle()+145)
        endArrowWing1.setLength(4)

        endArrowWing2 = QtCore.QLineF()
        endArrowWing2.setP1(self.line().p2())
        endArrowWing2.setAngle(self.line().angle()-145)
        endArrowWing2.setLength(4)

        return [startArrowWing1, startArrowWing2, endArrowWing1, endArrowWing2]

    def boundingRect(self) -> QtCore.QRectF:
        arrowLines = self.getArrowLines()

        xMin = min([line.x1() for line in arrowLines] + [line.x2() for line in arrowLines])
        yMin = min([line.y1() for line in arrowLines] + [line.y2() for line in arrowLines])
        xMax = max([line.x1() for line in arrowLines] + [line.x2() for line in arrowLines])
        yMax = max([line.y1() for line in arrowLines] + [line.y2() for line in arrowLines])

        return QtCore.QRectF(xMin, yMin, xMax - xMin, yMax - yMin)

# Contains a whole bunch of options and brushes to draw a QGraphicsScene @ getScene()
class KeyboardQ():
    paddingTop      = 0
    paddingBottom   = 0
    paddingLeft     = 0
    paddingRight    = 0

    topLeft = KbCorner(Corner.TOPLEFT)
    topRight = KbCorner(Corner.TOPRIGHT)
    bottomLeft = KbCorner(Corner.TOPRIGHT)
    bottomRight = KbCorner(Corner.TOPRIGHT)

    padFromReserved:    bool = True
    paddingToHighlight: Padding = Padding.NONE
    switchType:         Key.SwitchType = Key.SwitchType.CHERRY_MX
    stabilizerType:     Key.StabilizerType = Key.StabilizerType.CHERRY_COSTAR
    kerf:               float = 0
    shape:              KbShape = KbShape.RECTANGULAR
    thickness:          float = 1.5
    flipStabilizers:    bool = False
    showKeyCap:         bool = True
    showCutout:         bool = True
    rotateSwitch:       bool = False

    keyCount = {}
    stabCount = {}

    keyCapBrush         = QtGui.QBrush(QtGui.QColor(221, 204, 186, 255))
    keyCapSideBrush     = QtGui.QBrush(QtGui.QColor(185, 169, 151, 255))
    noBrush             = QtGui.QBrush(QtCore.Qt.transparent)
    reservedBrush       = QtGui.QBrush(QtGui.QColor(100, 175, 175, 100))
    hoverBrush          = QtGui.QBrush(QtGui.QColor(100, 175, 175, 100))
    switchBrush         = QtGui.QBrush(QtGui.QColor(0, 0, 0, 255))
    paddingBrush        = QtGui.QBrush(QtCore.Qt.green)
    noPen               = QtCore.Qt.NoPen
    keyboardPlateBrush  = QtGui.QBrush(QtGui.QColor(240, 236, 221, 255))
    dimensionsPen       = QtGui.QPen(keyCapSideBrush.color(), 0.5)

    kbPoly = QtGui.QPolygonF()

    # If the number of same (same orientation and angle) keys exceeds this cap
    # a point array will be used in FreeCAD rather than cloning and positioning 
    # over and over
    cloneCap = 1
    renderArrows = True

    def getScene(self, skb: serial.Keyboard) -> QtWidgets.QGraphicsScene:
        self.keyCount = {}    
        self.stabCount = {}
        self.scene = QtWidgets.QGraphicsScene()
        
        if not self.showCutout:
            self.switchBrush = self.noBrush

        keyInfoList = [self.getKeyInfos(key) for key in skb.keys]
        for keyInfo in keyInfoList:
            self.addKeyToScene(keyInfo)
            self.__incrementKeyAndStabCount(keyInfo)

        self.kbGi = self.addKeyboardBackgroundToScene()
        self.checkSwitchBounds()

        if self.renderArrows:
            self.addDimensionsArrows(self.kbGi)

        self.stabDifficultyReport()

        return self.scene
    
    # Returns list of QGraphicsItems to pad from. 
    # In case of self.padFromReserved = True it's always a single item but it
    # allows us to use one code path.
    def addKeyToScene(self, keyInfo: Key.KeyReservedSpace):
        padding = QtCore.QPointF(self.paddingLeft, self.paddingTop)
        centerIncPadding = keyInfo.keyCenter + padding
        originIncPadding = keyInfo.originPoint + padding
        reservedSpaceGi = KeyReservedSpaceGi(keyInfo, self.hoverBrush, self.switchBrush)
        reservedSpaceGi.setAcceptHoverEvents(True)
        reservedSpaceGi.setPen(QtCore.Qt.NoPen)
        reservedSpaceGi.setBrush(QtCore.Qt.NoBrush)
        reservedSpaceGi.setPos(centerIncPadding)
        reservedSpaceGi.setData(1, self)
        self.scene.addItem(reservedSpaceGi)
        if self.showKeyCap:
            o = 1.

            keyCapGi = KbKeyGi(keyInfo.keyCapFootprint, reservedSpaceGi, 1, 2, 3, o)
            keyCapGi.setPen(self.noPen)
            keyCapGi.setBrush(self.keyCapBrush)
            keyCapGi.setSideBrush(self.keyCapSideBrush)
            keyCapGi.setLabels(keyInfo.key.labels)
            tt = '''
<table>
<tr><th>Width: </th><td>{}</td></tr>
<tr><th>Height: </th><td>{}</td></tr>
<tr><th>Flipped: </th><td>{}</td></tr>
<tr><th>Keysize: </th><td>{}</td></tr>
<tr><th>Stabiliser:</th><td>{}</td></tr>
</table>'''
            keyCapGi.setToolTip(tt.format(
                keyInfo.key.width,
                keyInfo.key.height,
                '🗹' if keyInfo.flipped else '☒',
                Key.SwitchType.GetSwitchTypeClass(self.switchType).difficulty(keyInfo.getBiggestSize()),
                keyInfo.stabType

            ))

        if keyInfo.hasOriginPoint():
            originPointGi = self.scene.addEllipse(
                self.createCircleRect(originIncPadding, 4),
                self.noPen, QtGui.QBrush(QtCore.Qt.white)
            )
            originPointGi.setZValue(2)
            reservedSpaceGi.setData(2, originPointGi)
            originPointGi.hide()

        if keyInfo.isRotated():
            reservedSpaceGi.setTransformOriginPoint(originIncPadding - centerIncPadding)
            reservedSpaceGi.setRotation(keyInfo.key.rotation_angle)

        self.kbPoly = self.kbPoly.united(reservedSpaceGi.rect())

    def getKeyReservedSpaceGis(self) -> typing.List[KeyReservedSpaceGi]:
        scene: QtWidgets.QGraphicsScene = self.scene
        return [i for i in scene.items() if isinstance(i, KeyReservedSpaceGi)]
    
    # Calculate a Convex hull using the Graham scan algorithm.
    def monotoneChain(self, polygon):
        points = list(polygon)
        # Remove duplicate points
        uniquePoints = []
        for point in points:
            if point not in uniquePoints:
                uniquePoints.append(point)
        points = uniquePoints
        # Sort points by x-coordinate, then by y-coordinate
        points.sort(key=lambda p: (p.x(), p.y()))
        lower = []
        for point in points:
            while len(lower) >= 2 and ((lower[-1].y() - lower[-2].y()) * (point.x() - lower[-1].x()) <= (point.y() - lower[-1].y()) * (lower[-1].x() - lower[-2].x())):
                lower.pop()
            lower.append(point)
        upper = []
        for point in reversed(points):
            while len(upper) >= 2 and ((upper[-1].y() - upper[-2].y()) * (point.x() - upper[-1].x()) <= (point.y() - upper[-1].y()) * (upper[-1].x() - upper[-2].x())):
                upper.pop()
            upper.append(point)
        hull = lower[:-1] + upper[:-1]
        return QPolygonF(hull)


    def addKeyboardBackgroundToScene(self) -> QtWidgets.QGraphicsPathItem:
        kbGi = None

        if self.shape == KbShape.RECTANGULAR:
            # For arcTo think of a clock 🕑 where 15:00 = 0, 12:00 = 90,  18:00 = 270 and 21:00 = 180.
            # So 3 o clock is the 0 point and it's going counterclockwise.
            kbData = self.getKbIntermediaryData()
            # As we're drawing counterclockwise and first the border and then the corner
            # it's important we start with the top border (as the top left corner is up first)
            borders = [kbData.topBorder, kbData.leftBorder, kbData.bottomBorder, kbData.rightBorder]

            # Start at the top left corner (the left of the top border)
            path = QtGui.QPainterPath(borders[0].p2())        
            for border, corner in zip(borders, Corner.Corners()):
                path.lineTo(border.p2())
                if self.getCorner(corner).style == CornerStyle.ROUNDED:
                    path.arcTo(
                        kbData.getCornerRect(corner),
                        kbData.getAngle(corner),
                        90
                    )
                elif self.getCorner(corner).style == CornerStyle.ANGLED:
                    path.lineTo(kbData.getCornerLine(corner).p2())
                # else self.getCorner(corner).style == CornerStyle.RIGHT
                # sorts itself out as there's no connecting line in between, the line themselves connect

                self.showCornerIssues(corner, kbData)
        else:
            path = QtGui.QPainterPath()

            keySpaceGis = self.getKeyReservedSpaceGis()
            unitedPolygon = QPolygonF()
            for keySpaceGi in keySpaceGis:
                polyGi = keySpaceGi.Grow(self.paddingTop)
                unitedPolygon = unitedPolygon.united(polyGi.mapToScene(polyGi.polygon()))
                
            convexHull = self.monotoneChain(unitedPolygon)
            path.addPolygon(convexHull)

        kbGi = self.scene.addPath(path, self.noPen, self.keyboardPlateBrush)
        kbGi.setZValue(-2)
        self.highlightPadding(path)

        return kbGi
    
    def getCorner(self, corner: Corner) -> KbCorner:
        return getattr(self, corner.value)

    #Checks
    def showCornerIssues(self, corner: Corner, kbData: KbIntermediaryData):
        rect = kbData.getArcBbox(corner)
        intersects = False
        for otherCorner in Corner.Corners():
            if otherCorner != corner:
                otherRect = kbData.getArcBbox(otherCorner)
                if rect.intersects(otherRect):
                    intersects = True
                    break
        if intersects:
            issueBrush = QtGui.QBrush(QtGui.QColor(255, 0, 0, 100))
            self.scene.addRect(kbData.getArcBbox(corner), self.noPen, issueBrush)

    def highlightPadding(self, path: QtGui.QPainterPath):
        boundingBox = path.boundingRect()
        rect = QtCore.QRectF(boundingBox)
        
        if self.paddingToHighlight == Padding.LEFT:
            rect.translate(self.paddingLeft, 0)
        elif self.paddingToHighlight == Padding.TOP:
            rect.translate(0, self.paddingTop)
        elif self.paddingToHighlight == Padding.RIGHT:
            rect.translate(-self.paddingRight, 0)
        elif self.paddingToHighlight == Padding.BOTTOM:
            rect.translate(0, -self.paddingBottom)
        elif self.paddingToHighlight == Padding.ALL:
            rect = QtCore.QRectF(boundingBox.x() + self.paddingLeft,
                boundingBox.y() + self.paddingTop,
                boundingBox.width() - (self.paddingLeft + self.paddingRight),
                boundingBox.height() - (self.paddingTop + self.paddingBottom))

        rectPath = QtGui.QPainterPath()
        rectPath.addRect(rect)

        result = path - rectPath
        highlightPad = self.scene.addPath(result, self.noPen, self.paddingBrush)
        highlightPad.setZValue(-1)

    # Checks if the switches are within bounds, paints them red if not.
    def checkSwitchBounds(self):
        outsidePath = QtGui.QPainterPath()
        outsidePath.addRect(self.scene.sceneRect())
        outsidePath = outsidePath.subtracted(self.kbGi.path())
        outOfBoundItems = self.scene.items(outsidePath)
        switchItems = [i for i in outOfBoundItems if isinstance(i, SwitchGi)]
        for switchItem in switchItems:
            if self.showCutout:
                switchItem.setBrush(QtGui.QBrush(QtGui.QColor(255,0,0,175)))
            else:
                switchItem.setBrush(QtGui.QBrush(QtCore.Qt.transparent))
    
    # packages all the information up neatly to draw a keyboard without having to
    # do any further calculations
    def getKbIntermediaryData(self) -> KbIntermediaryData:
        cutouts = []
        if self.padFromReserved:
            cutouts = [item for item in self.scene.items() if isinstance(item, KeyReservedSpaceGi)]
        else:
            cutouts = [item for item in self.scene.items() if isinstance(item, SwitchGi)]
        
        kbRect: QtCore.QRectF = self.getKeyboardRect(cutouts)
        self.difference = kbRect.topLeft() - QtCore.QPointF(0, 0)

        topLeftRect = QtCore.QRectF(kbRect.topLeft(), self.topLeft.getCornerRectSize())

        trS: QtCore.QRectF = self.topRight.getCornerRectSize()
        topRightRect = QtCore.QRectF(kbRect.topRight() - QtCore.QPointF(trS.width(), 0), trS)

        blS: QtCore.QRectF = self.bottomLeft.getCornerRectSize()
        bottomLeftRect = QtCore.QRectF(kbRect.bottomLeft() - QtCore.QPointF(0, blS.height()), blS)

        brS: QtCore.QRectF = self.bottomRight.getCornerRectSize()
        bottomRightRect = QtCore.QRectF(kbRect.bottomRight() - QtCore.QPointF(brS.width(), brS.height()), brS)

        leftBorder = QtCore.QLineF(
            topLeftRect.left(), topLeftRect.center().y(),
            bottomLeftRect.left(), bottomLeftRect.center().y()
        )
        bottomBorder = QtCore.QLineF(
            bottomLeftRect.center().x(), bottomLeftRect.bottom(),
            bottomRightRect.center().x(), bottomRightRect.bottom()
        )
        rightBorder = QtCore.QLineF(
            bottomRightRect.right(), bottomRightRect.center().y(),
            topRightRect.right(), topRightRect.center().y()
        )
        topBorder = QtCore.QLineF(
            topRightRect.center().x(), topRightRect.top(),
            topLeftRect.center().x(), topLeftRect.top()
        )

        if self.topLeft.style == CornerStyle.RIGHT:
            leftBorder.setP1(kbRect.topLeft())
            topBorder.setP2(kbRect.topLeft())
        if self.bottomLeft.style == CornerStyle.RIGHT:
            leftBorder.setP2(kbRect.bottomLeft())
            bottomBorder.setP1(kbRect.bottomLeft())
        if self.bottomRight.style == CornerStyle.RIGHT:
            bottomBorder.setP2(kbRect.bottomRight())
            rightBorder.setP1(kbRect.bottomRight())
        if self.topRight.style == CornerStyle.RIGHT:
            rightBorder.setP2(kbRect.topRight())
            topBorder.setP1(kbRect.topRight())

        bottomLeftCorner  = QtCore.QLineF(leftBorder.p2(), bottomBorder.p1())
        bottomRightCorner = QtCore.QLineF(bottomBorder.p2(), rightBorder.p1())
        topRightCorner    = QtCore.QLineF(rightBorder.p2(), topBorder.p1())
        topLeftCorner     = QtCore.QLineF(topBorder.p2(), leftBorder.p1())

        return KbIntermediaryData(
            leftBorder, bottomBorder, rightBorder, topBorder, 
            topLeftRect, bottomLeftRect, bottomRightRect, topRightRect,
            bottomLeftCorner, bottomRightCorner, topRightCorner, topLeftCorner
        )

    # Calculates the keyboard QRectF including padding taking into account where the padding starts from
    def getKeyboardRect(self, cutouts=typing.List[QtWidgets.QGraphicsItem]) -> QtCore.QRectF:
        lowestCutoutX = lowestCutoutY = 999999
        highestCutoutX = highestCutoutY = 0
        for cutout in cutouts:
            #Type hinting below helps Visual Studio Code figure things out
            cutout: QtWidgets.QGraphicsItem = cutout
            bbox = cutout.sceneBoundingRect()
            lowestCutoutX = min(lowestCutoutX, bbox.left())
            lowestCutoutY = min(lowestCutoutY, bbox.top())
            highestCutoutX = max(highestCutoutX, bbox.right())
            highestCutoutY = max(highestCutoutY, bbox.bottom())

        keyboardRect = QtCore.QRectF(
            lowestCutoutX - self.paddingLeft,
            lowestCutoutY - self.paddingTop,
            highestCutoutX - lowestCutoutX + self.paddingLeft + self.paddingRight,
            highestCutoutY - lowestCutoutY + self.paddingTop + self.paddingBottom,
        )
        # To prevent an odd coordinate system 
        # (mainly makes things easier in the FreeCADKeyboard subclass)
        # move this rectangle to 0, 0 before returning it.
        #keyboardRect.setTopLeft(QtCore.QPointF(0, 0))

        return keyboardRect
    
    def addDimensionsArrows(self, kbGi: QtWidgets.QGraphicsPathItem):
        kbRect = kbGi.boundingRect()

        widthLine = ArrowLine(
            kbRect.bottomLeft().x(), kbRect.bottomLeft().y() + 5,
            kbRect.bottomRight().x(), kbRect.bottomRight().y() + 5
        )
        widthLine.setPen(self.dimensionsPen)
        widthLine.textGi.setBrush(QtGui.QBrush(self.dimensionsPen.color()))
        self.scene.addItem(widthLine)

        heightLine = ArrowLine(
            kbRect.bottomLeft().x() - 5, kbRect.bottomLeft().y(),
            kbRect.topLeft().x() - 5, kbRect.topLeft().y()
        )
        heightLine.setPen(self.dimensionsPen)
        heightLine.textGi.setBrush(QtGui.QBrush(self.dimensionsPen.color()))
        self.scene.addItem(heightLine)

    def createCircleRect(self, point: QtCore.QPointF, circleSize: float) -> QtCore.QRectF:
        halfSize = circleSize/2
        return QtCore.QRectF(point - QtCore.QPointF(halfSize, halfSize), QtCore.QSizeF(circleSize, circleSize))

    def stabKeyDifficultyReport(self) -> KeyAndStabDifficultyReports:
        keyDifficulties = []
        unsupportedKeysize = False
        totalKeyCount = 0
        keyClass: Key.CherryMx = Key.SwitchType.GetSwitchTypeClass(self.switchType) 
        
        for unit, count in self.keyCount.items():
            ud = UnitCountAndDifficulty(
                sizeInU=unit,
                count=count,
                difficulty= keyClass.difficulty(Key.KeyReservedSpace.StrToFloat(unit))
            )
            keyDifficulties.append(ud)
            totalKeyCount += count
            if ud.difficulty == Key.Difficulty.CUSTOM:
                unsupportedKeysize = True
        keyDifficultyReport = UnitDifficultyReport(
            keyDifficulties,
            totalKeyCount,
            unsupportedKeysize,
        )

        return KeyAndStabDifficultyReports(
            keyDifficultyReport, self.stabDifficultyReport()
        )

    def stabDifficultyReport(self) -> UnitDifficultyReport:
        stabDifficulties = []
        unsupportedStabsize = False
        totalStabCount = 0
        keyClass: Key.BaseKey = Key.SwitchType.GetSwitchTypeClass(self.switchType)
        
        for unit, count in self.stabCount.items():
            ud = UnitCountAndDifficulty(
                sizeInU = unit,
                count = count,
                difficulty = keyClass.difficulty(Key.KeyReservedSpace.StrToFloat(unit))
            )
            stabDifficulties.append(ud)
            totalStabCount += count
            if ud.difficulty == Key.Difficulty.CUSTOM:
                unsupportedStabsize = True
        stabDifficultyReport = UnitDifficultyReport(
            stabDifficulties,
            totalStabCount,
            unsupportedStabsize
        )
        return stabDifficultyReport

    def __incrementKeyAndStabCount(self, keyReservedSpace: Key.KeyReservedSpace):
        # Variable names need to start with a letter (not a number)
        floatBiggestSize = keyReservedSpace.getBiggestSize()
        size = keyReservedSpace.FloatToU(floatBiggestSize)

        if size in self.keyCount:
            self.keyCount[size] += 1
        else:
            self.keyCount[size] = 1

        if floatBiggestSize >= 2:
            realStabSize = size
            if Key.Stabilizer.Size.Is2uStabilised(floatBiggestSize):
                realStabSize = '2u'
            if realStabSize in self.stabCount:
                self.stabCount[realStabSize] += 1
            else:
                self.stabCount[realStabSize] = 1

    def hasRightAngles(self):
        return self.allCornersAreEqual() and self.cornerRadiusTopLeft == 0

    def allCornersAreEqual(self):
        return self.cornerRadiusTopLeft == self.cornerRadiusTopRight \
            == self.cornerRadiusBottomLeft == self.cornerRadiusBottomRight

    def getKeyInfos(self, key: serial.Key) -> Key.KeyReservedSpace:
        switchClass = Key.SwitchType.GetSwitchTypeClass(self.switchType)        
        keyInfo = switchClass(
            key, 
            self.stabilizerType, 
            self.kerf, 
            self.flipStabilizers,
            self.rotateSwitch
        )

        return keyInfo