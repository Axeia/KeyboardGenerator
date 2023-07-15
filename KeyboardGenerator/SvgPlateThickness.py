import xml.etree.ElementTree as ET
import math
from PySide2 import QtGui, QtCore
from enum import Enum
import os, sys, inspect

class SvgPlateThickness():
    plateHeight = 2.0

    def getByteArray(self):
        filePath = os.path.realpath(os.path.abspath(os.path.split(inspect.getfile( inspect.currentframe() ))[0]))
        filePath += os.path.sep + 'svgs' + os.path.sep + 'plate-thickness.svg'
        #FreeCAD.Console.PrintMessage(filePath)
        self.tree = ET.parse(filePath)
        self.root = self.tree.getroot()

        self.adjustPlateThickness()

        return ET.tostring(self.root)

    def adjustPlateThickness(self):
        for direction in ['left', 'right']:
            plate = self.tree.find(f'.//*[@id="plate-{direction}"]')
            plate.set('height', str(self.plateHeight * 10))

            distanceLine = self.tree.find(f'.//*[@id="plate-distance-line-{direction}"]')
            y1 = int(distanceLine.get('y1'))
            y1 += (10 * self.plateHeight) + 1
            distanceLine.set('y2', str(y1))

            text = self.tree.find(f'.//*[@id="plate-txt-{direction}"]')
            text.text = str(self.plateHeight)+"mm"
