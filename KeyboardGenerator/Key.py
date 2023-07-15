import serial
import typing
from enum import Enum
from typing import List
from PySide2.QtCore import QPointF as Qpf
from PySide2 import QtGui, QtCore
from abc import abstractmethod

class Component(Enum):
    ENTIRE = 0
    LEFT = 1
    RIGHT = 2

class Difficulty(Enum):
    CUSTOM = 0
    EASY = 1
    MEDIUM = 2
    HARD = 3

class StabilizerType(str, Enum):
    CHERRY_COSTAR = 'Cherry+Costar'
    CHERRY = 'Cherry'
    COSTAR = 'Costar'
    ALPS = 'Alps'

    def GetComponents(stabType) -> typing.List['StabilizerType']:
        if stabType == StabilizerType.COSTAR or stabType == StabilizerType.ALPS:
            return [Component.LEFT, Component.RIGHT]
        else:
            return [Component.ENTIRE]


class SwitchType(str, Enum):
    CHERRY_MX = 'Cherry MX'
    CHERRY_MX_OPENABLE = 'Cherry MX Openable'
    CHERRY_MX_ALPS = 'Cherry MX+Alps'
    ALPS = 'Alps'

    @classmethod
    def GetSwitchTypeClass(self, switchType):
        switchClassMap = {
            SwitchType.CHERRY_MX:           CherryMx,
            SwitchType.CHERRY_MX_ALPS:      CherryMxAlps,
            SwitchType.CHERRY_MX_OPENABLE:  CherryMxOpenable,
            SwitchType.ALPS:                Alps
        }
        return switchClassMap[switchType]


# Typically a 19.05x19.05 square
# But may be rotated and/or some kind of multiplication of 19.05 (or 19mm)
class KeyReservedSpace():
    ONE_U:         float = 19.05
    KEYCAP_OFFSET: float = 0.5025  # = (19.05 - 18) / 2
    
    autoModifiedStab:  bool = False #Only Alps keys combined with alps stab might give a true
    isJShaped:         bool = False
    keyCenter:         QtCore.QPointF = None
    # Could be rotated resulting in a polygon rather than a qrectf so might
    # as well just start with a polygon
    reservedSpace:      QtGui.QPolygonF = None
    keyPlacementPoint:  QtCore.QPointF = None
    originPoint:        QtCore.QPointF = None
    stabType:           StabilizerType = StabilizerType.CHERRY_COSTAR
    flipped:            bool = False
    rotateSwitch:       bool = False

    def getMidPoint(self) -> QtCore.QPointF:
        return self.reservedSpace.boundingRect().center()

    def __init__(
        self, 
        key: serial.Key, 
        stab: StabilizerType = StabilizerType.CHERRY_COSTAR, 
        kerf: float = 0, 
        flipped: bool = False,
        rotateSwitch: bool = False
    ):
        self.kerf = kerf
        self.stabType = stab
        self.key = key
        self.flipped = flipped
        self.rotateSwitch = self.shouldBeStabilised() and rotateSwitch

        self.originPoint = self._createOffsetPointU(key.rotation_x, key.rotation_y)
        
        self.transf = QtGui.QTransform().rotate(key.rotation_angle)

        xMm = key.width * self.ONE_U
        yMm = key.height * self.ONE_U
        self.reservedSpace = QtCore.QRectF(xMm * 0.5 * -1, yMm * 0.5 * -1, xMm, yMm)

        self.keyCapFootprint = QtCore.QRectF(
            (self.reservedSpace.width()  * 0.5 * -1) + self.KEYCAP_OFFSET,
            (self.reservedSpace.height() * 0.5 * -1) + self.KEYCAP_OFFSET,
            self.reservedSpace.width()  - (2 * self.KEYCAP_OFFSET),
            self.reservedSpace.height() - (2 * self.KEYCAP_OFFSET)
        )
        self.keyCenter = self._createOffsetPointU(
            key.x + (key.width  * 0.5),
            key.y + (key.height * 0.5)
        )

    def _createOffsetPointU(self, x: float, y: float) -> QtCore.QPointF:
        return QtCore.QPointF((x * self.ONE_U), (y * self.ONE_U))

    def hasOriginPoint(self) -> bool:
        return (self.key.rotation_x != 0. or self.key.rotation_y != 0.) \
            and self.key.rotation_angle != 0

    def isRotated(self) -> bool:
        return self.key.rotation_angle != 0
    
    def isVertical(self) -> bool:
        return self.key.height > self.key.width
    
    @abstractmethod
    def isStandardSize(self) -> bool:
        pass
    
    def getStabParts(self) -> typing.List[QtGui.QPolygonF]:
        return self.__getStabParts(self.stabType)
    
    def __getStabParts(self, stabType: StabilizerType) -> typing.List[QtGui.QPolygonF]:
        components = StabilizerType.GetComponents(stabType)
        angle = 90 if self.isVertical() else 0
        
        if self.flipped:
            angle += 180

        polygons = [self.footprint()]
        for component in components:
            stabOffset = self.GetStabOffset(self.getBiggestSize())
            polygons.append(Stabilizer.footprint(
                self.kerf, stabOffset, component, angle, self.stabType
            ))

        if Component.ENTIRE in components:
            unifiedPolygon = QtGui.QPolygonF()
            for polygon in polygons:
                unifiedPolygon = unifiedPolygon.united(polygon)
            polygons = [unifiedPolygon]

        return polygons

    @classmethod
    def footprintMockup(cls, kerf: float = 0.) -> QtGui.QPolygonF:
        k = kerf

        return QtGui.QPolygonF([
            Qpf(7-k, -7+k),  Qpf(7-k, 7-k), Qpf(-7+k, 7-k),
            Qpf(-7+k, -7+k), Qpf(7-k, -7+k)
        ])

    # When overwriting this make sure to call .rotateSwitchIfNeeded
    def footprint(self):
        footprint = self.__class__.footprintMockup(self.kerf)
        if self.rotateSwitch:
            transform = QtGui.QTransform()
            transform.rotate(90)
            footprint = transform.map(footprint)

        return footprint

    @classmethod
    def GetStabOffset(self, size: float) -> float:
        # Note: 19.05 is used instead of KeyReservedSpace.ONE_U as
        # any purchased stabilizers would still stick to the regular sizing
        # Everything above 8u gets normalized to an 8u stabilizer
        if size > 8:
            size = 8
        # Everything between 2u and 3u gets a 2u stabilizer
        if size >= self.minStabSize and size < 3:
            return 1.25 * 19.05 * 0.5
        # Everything between 2u and 8u gets their stabilizer according to this formula
        # For standard stabilizer sizes see @StabilizerSize
        elif size >= 3 and size <= 8:
            return (size - 1) * 19.05 * 0.5
        # Uncalculable - shouldn't have been passed to this, by returning 0
        # any calculations based should at least complete unmodified instead of
        # erroring out. Without this the result would have been 'None'.
        else:
            return 0.0

    @abstractmethod
    def shouldBeStabilised(self) -> bool:
        pass

    @staticmethod
    def FloatToU(sizeInU: float) -> str:        
        return '{:g}u'.format(sizeInU)

    @staticmethod
    def StrToFloat(strU: float) -> float:
        return float(strU.rstrip('u'))

    def getBiggestSize(self) -> float:
        return max([self.key.width, self.key.height])
    
    def hasSameOriginPoint(self, other: 'KeyReservedSpace') -> bool:
        return other is not None \
            and self.hasOriginPoint() \
            and self.originPoint == other.originPoint

# Basically just here so elsewhere it doesn't look like a key is CherryMx when
# it isn't. CherryMx for all intents however is the base class
class BaseKey(KeyReservedSpace):
    __easySizesInU = [1, 1.25, 1.5, 1.75, 2, 2.25, 2.75, 6.25, 7]
    __mediumSizesInU = [3, 4]
    __hardSizesInU = [2.5, 4.5, 5.5, 6.5, 8, 9, 10]
    __sizesInU = __easySizesInU + __mediumSizesInU + __hardSizesInU
    minStabSize: float = 2

    def __init__(
        self,  
        key: serial.Key, 
        stab: StabilizerType, 
        kerf: float = 0, 
        flipped: bool = False,
        rotateSwitch: bool = False
    ):
        super().__init__(key, stab, kerf, flipped, rotateSwitch)
        self.poly = self.footprint()

    @classmethod
    def difficulty(cls, keySize: float) -> bool:
        if keySize in cls.__easySizesInU:
            return Difficulty.EASY
        elif keySize in cls.__mediumSizesInU:
            return Difficulty.MEDIUM
        elif keySize in cls.__hardSizesInU:
            return Difficulty.HARD
        else:
            return Difficulty.CUSTOM

    def shouldBeStabilised(self):
        return self.getBiggestSize() >= self.minStabSize

    @classmethod
    def IsValid(self, sizeInU: float):
        return sizeInU in self.__sizesInU
        
    def getStabSizeU(self) -> str:
        biggestSize = self.getBiggestSize()
        if biggestSize > 8:
            return '8u'
        if biggestSize >= self.minStabSize and biggestSize < 3:
            return '2u'
        else: #size >= 3 and size < 8
            return BaseKey.FloatToU(biggestSize)

    def isStandardSize(self) -> bool:
        return self.__class__.IsValid(self.key.width) and self.__class__.IsValid(self.key.height)
    pass

class CherryMx(BaseKey):
    pass

class CherryMxOpenable(CherryMx):
    @classmethod
    def footprintMockup(cls, kerf: float = 0.) -> QtGui.QPolygonF:
        k = kerf
        return QtGui.QPolygonF([
            Qpf(7-k,   -7+k),    Qpf(7-k,   -6+k),
            Qpf(7.8-k, -6+k),    Qpf(7.8-k,  -2.9-k),
            Qpf(7-k,   -2.9-k),  Qpf(7-k,     2.9+k),
            Qpf(7.8-k,  2.9+k),  Qpf(7.8-k,   6-k),
            Qpf(7-k,    6-k),    Qpf(7-k,     7-k),
            Qpf(-7+k,    7-k),   Qpf(-7+k,    6-k),
            Qpf(-7.8+k,  6-k),   Qpf(-7.8+k,  2.9+k),
            Qpf(-7+k,    2.9+k), Qpf(-7+k,   -2.9-k),
            Qpf(-7.8+k, -2.9-k), Qpf(-7.8+k, -6+k),
            Qpf(-7+k,   -6+k),   Qpf(-7+k,   -7+k),
            Qpf(7-k,   -7+k)
        ])


class CherryMxAlps(CherryMx):
    @classmethod
    def footprintMockup(cls, kerf: float = 0.) -> QtGui.QPolygonF:
        k = kerf
        return QtGui.QPolygonF([
            Qpf( 7-k,   -7+k),   Qpf( 7-k,   -6.4+k), 
            Qpf( 7.8-k, -6.4+k), Qpf( 7.8-k,  6.4-k),
            Qpf( 7-k,    6.4-k), Qpf( 7-k,    7-k), 
            Qpf(-7+k,    7-k),   Qpf(-7+k,    6.4-k),
            Qpf(-7.8+k,  6.4-k), Qpf(-7.8+k, -6.4+k), 
            Qpf(-7+k,   -6.4+k), Qpf(-7+k,   -7+k), 
            Qpf( 7-k,   -7+k)
        ])


class Alps(CherryMx):
    __supportedStabSizes = {
        1.75:   11.938,
        2.0:    14.096,
        2.25:   14.096,
        2.75:   14.096,
        6.25:   41.859,
        6.5:    45.3
    }
    minStabSize: float = 1.75
    __cherryMinStabSize: float = 0

    def __init__(
        self, 
        key: serial.Key, 
        stab: StabilizerType = StabilizerType.CHERRY_COSTAR, 
        kerf: float = 0, 
        flipped: bool = False,
        rotateSwitch: bool = False
    ):
        self.__cherryMinStabSize = 2.0 #This doesn't work: super().__minStabSize
        super().__init__(key, stab, kerf, flipped, rotateSwitch)
        if stab == StabilizerType.ALPS and not Alps.IsSupportedStabSize(self.getBiggestSize()):
            self.stabType = StabilizerType.COSTAR
            self.autoModifiedStab = True

    @classmethod
    def footprintMockup(self, kerf: float = 0., rotation: float = 0) -> QtGui.QPolygonF:
        k = kerf
        return QtGui.QPolygonF([
            Qpf( 7.75-k, -6.4+k), Qpf( 7.75-k,  6.4-k),
            Qpf(-7.75+k,  6.4-k), Qpf(-7.75+k, -6.4+k),
            Qpf( 7.75-k, -6.4+k),
        ])

    @classmethod
    def GetStabOffset(cls, size: float) -> float:
        if cls.stabType == StabilizerType.ALPS and cls.IsSupportedStabSize(size):
            return Alps.__supportedStabSizes[size]
        else:
            return CherryMx.GetStabOffset(size)
    
    def calcStabOffset(self, size: float):
        if self.IsSupportedStabSize(self.getBiggestSize()):
            return Alps.GetStabOffset(size)
        else:
            return super.GetStabOffset(size)

    @classmethod
    def IsSupportedStabSize(self, size: float):
        return size in self.__supportedStabSizes.keys()

    def shouldBeStabilised(self):
        if self.stabType == StabilizerType.ALPS:
            return self.getBiggestSize() >= self.minStabSize
        else:
            return self.getBiggestSize() >= self.__cherryMinStabSize

class Stabilizer:
    class Size(CherryMx):
        # 2.5 is easy to stabilize (2u stabilizer) but hard to get a keycap for
        __TwoUSizesInU = [2, 2.25, 2.5, 2.75]
        __easySizesInU = [2, 2.25, 2.5, 2.75] + [6.25, 7]
        __mediumSizesInU = [3, 4]
        __hardSizesInU = [4.5, 5.5, 6.5, 8, 9, 10]
        __sizesInU = __easySizesInU + __mediumSizesInU + __hardSizesInU

        @classmethod
        def Difficulty(self, keySize: float) -> bool:
            if keySize in self.__easySizesInU:
                return Difficulty.EASY
            elif keySize in self.__mediumSizesInU:
                return Difficulty.MEDIUM
            elif keySize in self.__hardSizesInU:
                return Difficulty.HARD
            else:
                return Difficulty.CUSTOM

        @classmethod
        def Is2uStabilised(self, keySize: float) -> bool:
            return keySize in self.__TwoUSizesInU

        @classmethod
        def IsValid(self, sizeInU: float):
            return sizeInU in self.__sizesInU

        @classmethod
        def FloatToU(self, size: float):
            if self.Is2uStabilised(size):
                return '2u'
            else:
                return KeyReservedSpace.FloatToU(size)

        @classmethod
        def ShouldBeStabilised(self, size: float):
            return size >= 2

    @classmethod
    def footprintForKey(
        self,
        key: BaseKey,
        kerf: float,
        component: Component = Component.ENTIRE,
        stabType: StabilizerType = StabilizerType.CHERRY_COSTAR
    ) -> QtGui.QPolygonF:
        rotationAngle = 0
        if key.key.height > key.key.width:
            rotationAngle = 90

        size = key.getBiggestSize()

        return Stabilizer.footprint(
            kerf, 
            key.__class__.GetStabOffset(size),
            component, 
            stabType, 
            rotationAngle
        )

    # Similar to
    @classmethod
    def footprintForU(
        self,
        strU: str,
        kerf: float,
        component: Component = Component.ENTIRE,
        stabType: StabilizerType = StabilizerType.CHERRY_COSTAR,
        angle: float = 0
    ) -> QtGui.QPolygonF:
        size = KeyReservedSpace.StrToFloat(strU)
        return Stabilizer.footprint(kerf, size, component, stabType, angle)

    # Dimensions are from:
    # https://github.com/swill/kb_builder/blob/7e48baa83da6a82b00f333e98eb203f25058fae0/lib/builder.py#L354
    # unless stated otherwise.
    # Swill opted to write out the entire footprint, as we're using Qt and in an
    # attempt to keep things easier to read the choice was made here to only 
    # define half of the actual footprint and use QTransform to create the other 
    # half (the whole programming 'write once and re-use' mantra
    @classmethod
    def footprint(
        self,
        kerf:           float,
        width:          float,
        component:      Component = Component.ENTIRE,
        rotationAngle:  int = 0,
        stabType:       StabilizerType = StabilizerType.CHERRY
    ) -> QtGui.QPolygonF:
        k = kerf
        x = width
        poly = QtGui.QPolygonF()

        mirrorHorizontally = QtGui.QTransform()
        mirrorHorizontally.scale(-1, 1)

        poly = Stabilizer.GetLeftFootPrint(kerf, width, stabType)
        if component == Component.RIGHT:
            poly = mirrorHorizontally.map(poly)

        if stabType == StabilizerType.CHERRY or stabType == StabilizerType.CHERRY_COSTAR:
            # The options below are connected by a rectangle through the middle
            joiningRectBar = QtGui.QPolygonF([
                Qpf(-x+3.325-k,  2.3-k),
                Qpf(x+3.325-k,  2.3-k), Qpf(x+3.325-k, -2.3+k),
                Qpf(-x+3.325-k, -2.3+k)
            ])

            # right
            poly = poly.united(mirrorHorizontally.map(poly))
            #complete
            poly = poly.united(joiningRectBar) 

        transform = QtGui.QTransform()
        transform.rotate(rotationAngle)
        poly = transform.map(poly)

        return poly
    
    @classmethod
    def GetLeftFootPrint(cls, kerf: float, width: float, stabType: StabilizerType) -> QtGui.QPolygonF:
        k = kerf
        x = width
        if stabType == StabilizerType.COSTAR:
            return QtGui.QPolygonF([
                Qpf(-x+1.65-k, -7.1+k), Qpf(-x-1.65+k, -7.1+k),
                Qpf(-x-1.65+k,  7.1-k), Qpf(-x+1.65-k,  7.1-k),
                Qpf(-x+1.65-k, -7.1+k)
            ])
        # Based on https://github.com/swill/kad/blob/master/key.go#L365
        elif stabType == StabilizerType.ALPS:
            return QtGui.QPolygonF([
                Qpf(-x+1.333-k, 3.873-k), Qpf(-x-1.333+k, 3.873-k),
                Qpf(-x-1.333+k, 9.08-k),  Qpf(-x+1.333-k, 9.08-k),
                Qpf(-x+1.333-k, 3.873-k)
            ])
        elif stabType == StabilizerType.CHERRY:
            # left
            return QtGui.QPolygonF([
                Qpf(-x+3.325-k,  6.77-k), Qpf(-x+1.65-k,    6.77-k),
                Qpf(-x+1.65-k,   7.97-k), Qpf(-x-1.65+k,    7.97-k),
                Qpf(-x-1.65+k,   6.77-k), Qpf(-x-3.325+k,   6.77-k),
                Qpf(-x-3.325+k,  0.5-k),  Qpf(-x-4.2+k,     0.5-k),
                Qpf(-x-4.2+k,   -2.3+k),  Qpf(-x-3.325+k,  -2.3+k),
                Qpf(-x-3.325+k, -5.53+k), Qpf(-x+3.325-k,  -5.53+k),
                Qpf(-x+3.325-k,  6.77-k)
            ])
        else:  # StabilizerType.CHERRY_COSTAR
            #left
            return QtGui.QPolygonF([
                Qpf(-x+3.325-k,  6.77-k), Qpf(-x+1.65-k,   6.77-k),
                Qpf(-x+1.65-k,   7.75-k), Qpf(-x-1.65+k,   7.75-k),
                Qpf(-x-1.65+k,   6.77-k), Qpf(-x-3.325+k,  6.77-k),
                Qpf(-x-3.325+k,  0.5-k),  Qpf(-x-4.2+k,    0.5-k),
                Qpf(-x-4.2+k,   -2.3+k),  Qpf(-x-3.325+k, -2.3+k),
                Qpf(-x-3.325+k, -5.53+k), Qpf(-x-1.65+k,  -5.53+k),
                Qpf(-x-1.65+k,  -6.45+k), Qpf(-x+1.65-k,  -6.45+k),
                Qpf(-x+1.65-k,  -5.53+k), Qpf(-x+3.325-k, -5.53+k),
                Qpf(-x+3.325-k, -2.3+k),  Qpf(-x+3.325-k,  6.77-k)
            ])
