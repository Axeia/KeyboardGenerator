import os, sys
import time
from importlib import reload
import typing
from PySide2 import QtCore, QtGui, QtWidgets, QtSvg, QtWebEngineWidgets
import xml.etree.ElementTree as ET
import FreeCADGui
import FreeCAD
import copy
import re
import os.path
import json
from pathlib import Path
from abc import abstractmethod

cmdFolder = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Macro").GetString('MacroPath')
cmdFolder += os.path.sep + "KeyboardGenerator" + os.path.sep

iconFolder = cmdFolder + 'icons' + os.path.sep 
svgFolder = cmdFolder  + 'svgs' + os.path.sep

from pykle_serial import serial
import KeyboardQ
from KeyboardQ import Corner
import SvgPlateThickness
import FreeCADKeyboard
import Key

# FreeCAD caches modules 
# That makes development a PITA, this ensures they get freshly loaded
reload(serial)
reload(KeyboardQ)
reload(Key)
reload(FreeCADKeyboard)
reload(SvgPlateThickness)

SETTINGS = QtCore.QSettings(
    QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope,
    QtCore.QCoreApplication.applicationName(), 
    "KeyboardGenerator" 
)

DEFAULTS = {
    'KeyCapColor':          KeyboardQ.KeyboardQ.keyCapBrush.color(),
    'KeyCapSideColor':      KeyboardQ.KeyboardQ.keyCapSideBrush.color(),
    'KeyboardPlateColor':   KeyboardQ.KeyboardQ.keyboardPlateBrush.color(),
    'HoverColor':           KeyboardQ.KeyboardQ.hoverBrush.color(),
    'CloneCap':             KeyboardQ.KeyboardQ.cloneCap,
}
def GetColor(defaultName: str) -> QtGui.QColor:
    if defaultName in SETTINGS.allKeys():
        return QtGui.QColor(SETTINGS.value(defaultName))
    
    return DEFAULTS[defaultName]

def SettingsNameToVarName(setting: str):
    varName = setting.replace('Color', 'Brush')
    return varName[0].lower() + varName[1:]

class FocusDoubleSpinBox(QtWidgets.QDoubleSpinBox):
    focusInSignal = QtCore.Signal()
    focusOutSignal = QtCore.Signal()

    # Overwrite focusInEvent to emit a signal
    def focusInEvent(self, e):
        self.focusInSignal.emit()

    # Overwrite focusInEvent to emit a signal
    def focusOutEvent(self, e):
        self.focusOutSignal.emit()

class FocusPushButton(QtWidgets.QPushButton):    
    focusInSignal = QtCore.Signal()
    focusOutSignal = QtCore.Signal()

    # Overwrite focusInEvent to emit a signal
    def focusInEvent(self, e):
        self.focusInSignal.emit()

    # Overwrite focusInEvent to emit a signal
    def focusOutEvent(self, e):
        self.focusOutSignal.emit()


class ColorButton(QtWidgets.QPushButton):
    def __init__(self, settingsName: str, parent: QtWidgets.QWidget = None, showAlpha: bool = False):
        super().__init__(parent)
        self.settingsName = settingsName
        self.showAlpha = showAlpha
        varName = SettingsNameToVarName(settingsName)
        brush: QtGui.QBrush = getattr(KeyboardQ.KeyboardQ, varName)
        self.color = brush.color()
        self.createAndSetColorIcon()

    def createAndSetColorIcon(self):
        pm = QtGui.QPixmap(32, 16)
        # TODO Get this color from the theme or wherever FreeCADs own version
        # of this button gets it from. It's black in all included themes
        # But when set to no style sheet (and reopening the preferences window)
        # it's set to a grey color.
        pm.fill(QtGui.QColor(0, 0, 0))

        painter = QtGui.QPainter(pm)
        painter.setPen(QtGui.QPen(QtGui.QColor(160, 160, 164)))
        fillRect = QtCore.QRect(2, 2, pm.width()-4, pm.height()-4)
        
        # All colors in a keyboard are drawn on top of the keyboard plate
        # If the button uses alpha this make sure the preview on the button
        # actually looks like what it would look like in the preview.
        if self.showAlpha and self.settingsName != 'KeyboardPlateColor':
            painter.setBrush(QtGui.QBrush(GetColor('KeyboardPlateColor')))
            painter.drawRect(fillRect)

        painter.setBrush(self.color)
        painter.drawRect(fillRect)
        painter.end()

        self.setIcon(QtGui.QIcon(pm))
        self.setIconSize(pm.size())
        self.setText(self.getColorHex())

    def getColorHex(self):
        if self.showAlpha:
            return self.color.name(QtGui.QColor.HexArgb)
        else:
            return self.color.name(QtGui.QColor.HexRgb)


class ColorDefaultButton(ColorButton):
    def __init__(self, settingsName: str, parent: QtWidgets.QWidget = None, showAlpha: bool = False):
        super().__init__(settingsName, parent, showAlpha)
        self.clicked.connect(lambda: SETTINGS.remove(self.settingsName))
    

class ColorPickerButton(ColorButton):
    colorChanged = QtCore.Signal()

    def __init__(self, settingsName: str, parent: QtWidgets.QWidget = None, showAlpha: bool = False):
        super().__init__(settingsName, parent, showAlpha)
        self.clicked.connect(lambda: self.showColorDialog())
    

    def showColorDialog(self):
        colorDialog = QtWidgets.QColorDialog(self.color, self)
        colorDialog.setOption(colorDialog.ShowAlphaChannel, on=self.showAlpha)        
        if colorDialog.exec_():
            newColor = colorDialog.selectedColor()
            self.color = newColor
            SETTINGS.setValue(self.settingsName, self.getColorHex())
            self.createAndSetColorIcon()
            self.colorChanged.emit()

    def resetToDefault(self):
        brush = getattr(KeyboardQ.KeyboardQ, SettingsNameToVarName(self.settingsName))
        self.color = brush.color()

    def reload(self):
        self.color = GetColor(self.settingsName)
        self.createAndSetColorIcon()


class CornerTypeComboBox(QtWidgets.QComboBox):
    def __init__(self, qw: QtWidgets.QWidget, corner: Corner):
        super(CornerTypeComboBox, self).__init__(qw)

        self.transform = QtGui.QTransform()
        if corner == Corner.TOPLEFT or corner == None:
            self.transform.rotate(90)
        elif corner == Corner.TOPRIGHT:
            self.transform.rotate(180)
        elif corner == Corner.BOTTOMRIGHT:
            self.transform.rotate(270)

        iconRounded = self.createIcon('corner_rounded.svg')
        iconAngled = self.createIcon('corner_angled.svg')
        iconRight = self.createIcon('corner_right_angle.svg')

        self.addItem(iconRounded, "Rounded", KeyboardQ.CornerStyle.ROUNDED)
        self.addItem(iconAngled, "Angled", KeyboardQ.CornerStyle.ANGLED)
        self.addItem(iconRight, "Right", KeyboardQ.CornerStyle.RIGHT)

    def createIcon(self, angleSvgPath: str) -> QtGui.QIcon:
        icon = QtGui.QIcon()
        icon.addFile(iconFolder + angleSvgPath)
        pixmap = icon.pixmap(100, 100)
        rotatedPixmap = pixmap.transformed(self.transform)
        icon = QtGui.QIcon()
        icon.addPixmap(rotatedPixmap)
        icon.addPixmap(self.createTranslucentPixmap(rotatedPixmap), QtGui.QIcon.Disabled)

        return icon

    # Creates a reduced opacity pixmap, to be used as the icon when the button is disabled
    def createTranslucentPixmap(self, original: QtGui.QPixmap) -> QtGui.QPixmap:
        translucent = QtGui.QPixmap(original.size())
        translucent.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(translucent)
        painter.setOpacity(0.2)
        painter.drawPixmap(QtCore.QPoint(), original)
        painter.end()

        return translucent
    

class ResizableGraphicsView(QtWidgets.QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), QtCore.Qt.KeepAspectRatio)

class PointArrayIconComboBox(QtWidgets.QComboBox):
    def __init__(self, parent: QtWidgets.QWidget):
        super().__init__(parent)

    @abstractmethod
    def testAndSetHeight(self):
        self.addItem('test')
        height = self.height()
        self.setMaximumHeight(height)
        self.removeItem(0)
        self.view().setSpacing(5)

    def paintEvent(self, paint: QtGui.QPaintEvent):
        painter = QtWidgets.QStylePainter(self)
        painter.setPen(self.palette().color(QtGui.QPalette.Text))  # text?

        # draw the combobox frame, focusrect and selected etc
        opt = QtWidgets.QStyleOptionComboBox()
        self.initStyleOption(opt)
        painter.drawComplexControl(QtWidgets.QStyle.CC_ComboBox, opt)

        # draw the icon and text
        opt.currentIcon = QtGui.QIcon()
        painter.drawControl(QtWidgets.QStyle.CE_ComboBoxLabel, opt)

    def getIconPm(self, polygons, color='#ffffff') -> QtGui.QPixmap:
        baStabPreview = KeyboardQ.PointsSVG.PolygonsToSvg(color, *polygons)
        svgRender = QtSvg.QSvgRenderer(baStabPreview)
        svgRender.setAspectRatioMode(QtCore.Qt.KeepAspectRatio)

        pm = QtGui.QPixmap(self.iconSize())
        pm.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter()
        painter.begin(pm)
        svgRender.render(painter)
        painter.end()

        return pm

    def getGrayed(self, src):
        if isinstance(src, QtGui.QPixmap):
            src = src.toImage()

        dest = QtGui.QImage(src.size(), QtGui.QImage.Format_ARGB32)
        widthRange = range(src.width())
        for y in range(src.height()):
            for x in widthRange:
                pixel = src.pixelColor(x, y)
                alpha = pixel.alpha()
                if alpha < 255:
                    alpha //= 50
                gray = QtGui.qGray(src.pixel(x, y))
                pixel.setRgb(gray, gray, gray, alpha)
                dest.setPixelColor(x, y, pixel)
        return QtGui.QPixmap.fromImage(dest)


class KbSwitchComboBox(PointArrayIconComboBox):
    def __init__(self, parent: QtWidgets.QWidget):
        super(KbSwitchComboBox, self).__init__(parent)
        self.testAndSetHeight()
        for switchType in Key.SwitchType:
            self.addItem(self.getIcon(switchType), switchType.value, switchType)

        self.setStyleSheet(f"QComboBox QAbstractItemView {{min-width: 190px;}}")
        self.setMaximumWidth(140)

    def getIcon(self, switchType: Key.SwitchType) -> QtGui.QIcon:
        iconSize = QtCore.QSize(64, 64)
        self.setIconSize(iconSize)
        switchClass = Key.SwitchType.GetSwitchTypeClass(switchType)
        svg = KeyboardQ.PointsSVG.PolygonToSvg(switchClass.footprintMockup())
        svgRender = QtSvg.QSvgRenderer(svg)
        svgRender.setAspectRatioMode(QtCore.Qt.KeepAspectRatio)
        pm = QtGui.QPixmap(iconSize)
        pm.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter()
        painter.begin(pm)
        svgRender.render(painter)
        painter.end()
        icon = QtGui.QIcon(pm)

        return icon

class KbStabComboBox(PointArrayIconComboBox):
    def __init__(self, parent: QtWidgets.QWidget, switchType: Key.SwitchType):
        super(KbStabComboBox, self).__init__(parent)
        self.testAndSetHeight()
        self.switchType = switchType
        self.setIconSize(QtCore.QSize(64 * 2.25, 64))
        self.setMinimumWidth(80)
        self.setMaximumWidth(140)
        self.reCreateList()

        self.setStyleSheet(f"QComboBox QAbstractItemView {{min-width: 260px;}}")
        self.setMaximumWidth(140)

    # (re)creates the list
    def reCreateList(self, switch: Key.SwitchType = None):
        if switch is not None:
            self.switchType = switch

        currentIndex = self.currentIndex()
        if currentIndex == -1:
            currentIndex = 0

        self.clear()

        alpsSwitchTypes = [
            Key.SwitchType.CHERRY_MX_ALPS,
            Key.SwitchType.ALPS
        ] 
        for data in Key.StabilizerType:
            self.addItem(self.getIcon(data), data.value, data.value)
            item = self.model().item(self.count() - 1)

            enabled = True
            if data.value == Key.StabilizerType.ALPS:
                enabled = self.switchType in alpsSwitchTypes
            item.setEnabled(enabled)

        # Restore selection
        if self.model().item(currentIndex).isEnabled():
            self.setCurrentIndex(currentIndex)

    def getIcon(self, data) -> QtGui.QIcon:
        dummyKeyInfo = self.createDummyKeyInfo(data)
        polygons = dummyKeyInfo.getStabParts()
        icon = QtGui.QIcon(self.getIconPm(polygons, '#fff'))
        icon.addPixmap(self.getIconPm(polygons, '#aaa'), QtGui.QIcon.Disabled, QtGui.QIcon.Off)

        return icon

    def createDummyKeyInfo(self, stab: Key.StabilizerType) -> Key.KeyReservedSpace:
        dummyKey = serial.Key(stab)
        dummyKey.width = 2
        dummyKey.height = 1
        switchTypeClass = Key.SwitchType.GetSwitchTypeClass(self.switchType)
        dummyKeyInfo = switchTypeClass(dummyKey, stab)

        return dummyKeyInfo
    

class CollapsibleGroupBox(QtWidgets.QGroupBox):
    def __init__(self, title = "", parent = None):
        super().__init__(title, parent)
        self.setCheckable(True)
        self.setChecked(False)
        self.toggled.connect(self.showItems)
        self.setStyleSheet("QGroupBox{ padding-top: 1em; }")

    def showItems(self, checked):
        if self.layout():
            for i in range(self.layout().count()):
                item = self.layout().itemAt(i)
                if item.widget():
                    item.widget().setVisible(checked)


def cfgIntToQColor(argb):
    rgbaHex = format(argb, '08x')
    r, g, b = rgbaHex[:2], rgbaHex[2:4], rgbaHex[4:6]
    return QtGui.QColor(int(r, 16), int(g, 16), int(b, 16))

# Reads FreeCADs user configuration file and parses its content to extract
# The code editors preferences so we can replicate the look.
def GetUserConfig():
    userCfgPath = os.path.join(FreeCAD.ConfigGet('UserConfigPath'), 'user.cfg')
    tree = ET.parse(userCfgPath)
    root = tree.getroot()

    values = {}
    for group in root.findall(".//FCParamGroup[@Name='Editor']"):
        for element in group:
            name = element.get("Name")
            if name in ['String', 'Number', 'Keyword']:
                values[name] = cfgIntToQColor(int(element.get("Value")))
            elif name == 'Font':
                values['FontFamily'] = str(element.get("Value"))
            elif name == 'FontSize':
                values['FontSize'] = int(element.get('Value'))


    return values

userConfig = GetUserConfig()

class JSONHighlighter(QtGui.QSyntaxHighlighter):
    def __init__(self, parent = None):
        super().__init__(parent)
        self.rules = []
        
        # Numeric literals
        numberFormat = QtGui.QTextCharFormat()
        numberFormat.setForeground(userConfig['Number'])
        self.rules.append(
            (QtCore.QRegExp(r"\b[-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?\b"), numberFormat))

        # Strings
        stringFormat = QtGui.QTextCharFormat()
        stringFormat.setForeground(userConfig['String'])
        self.rules.append((QtCore.QRegExp(r"\".*\""), stringFormat))
        
        # Keys
        keyFormat = QtGui.QTextCharFormat()
        keyFormat.setForeground(userConfig['Keyword'])
        self.rules.append((QtCore.QRegExp(r"\b[a-zA-Z_][a-zA-Z0-9_]*\s*(?=:)\b"), keyFormat))

    def highlightBlock(self, text):
        for pattern, format in self.rules:
            expression = QtCore.QRegExp(pattern)
            index = expression.indexIn(text)
            while index >= 0:
                length = expression.matchedLength()
                self.setFormat(index, length, format)
                index = expression.indexIn(text, index + length)

# Tries to replicate the look of FreeCADs build in code editor by using the 
# same colors (obtained from)
class KeyboardCodeEditor(QtWidgets.QTextEdit):
    focusChanged = QtCore.Signal()

    def __init__(self, parent = None):
        super().__init__(parent)
        self.highlighter = JSONHighlighter(self.document())
        self.setCurrentFont(QtGui.QFont(
            userConfig['FontFamily'],
            userConfig['FontSize'])
        )
        

    def focusInEvent(self, e: QtGui.QFocusEvent) -> None:
        self.focusChanged.emit()
        return super().focusInEvent(e)
    
    def focusOutEvent(self, e: QtGui.QFocusEvent) -> None:
        self.focusChanged.emit()
        return super().focusOutEvent(e)

class PaddingDoubleSpinBox(QtWidgets.QDoubleSpinBox):
    focusInSignal = QtCore.Signal(KeyboardQ.Padding)
    focusOutSignal = QtCore.Signal(KeyboardQ.Padding)

    relatedSide: KeyboardQ.Padding = KeyboardQ.Padding.NONE

    def __init__(self, qw: QtWidgets.QWidget, side: KeyboardQ.Padding, ui: 'UiDialog'):
        super(PaddingDoubleSpinBox, self).__init__(qw)

        self.setValue(KeyboardQ.KeyboardQ.paddingTop)
        if side in KeyboardQ.Padding.Sides():
            self.setValue(getattr(KeyboardQ.KeyboardQ, side.ToVarName('padding{}')))

        self.relatedSide = side
        self.setSuffix('mm')
        self.setMinimum(0)
        self.setStyleSheet('min-width: 30px;')

        self.focusInSignal.connect(ui.highlightPreview)
        self.focusOutSignal.connect(ui.unHighlightPreview)
        self.valueChanged.connect(lambda: ui.reloadScene())

    # Overwrite focusInEvent to emit a signal
    def focusInEvent(self, e: QtGui.QFocusEvent):
        self.focusInSignal.emit(self.relatedSide)

    # Overwrite focusInEvent to emit a signal
    def focusOutEvent(self, e: QtGui.QFocusEvent):
        self.focusOutSignal.emit(self.relatedSide)


class UiDialog(QtWidgets.QDialog):
    defaultKeyboardLayoutPath = cmdFolder + os.path.sep + 'kg-logo.json'
    defaultKeyboardLayout = Path(defaultKeyboardLayoutPath).read_text(encoding="utf-8")

    messageOkDefault = "ⓘ FreeCAD may Freeze for a while after pressing Ok"
    messageNotOk = "⚠ Failed to parse the JSON5. Copy/paste from keyboard-layout.generator.com or a JSON file made by it"

    paddingToHighlight: KeyboardQ.Padding = KeyboardQ.Padding.NONE

    def __init__(self, appName: str, appVersion: str, userJSON5FilePath):
        super().__init__()
        self.userJSON5FilePath = userJSON5FilePath

        # Removes WindowContextHelpButtonHint (only the close button is needed)
        self.setWindowFlags(QtCore.Qt.WindowCloseButtonHint)
        self.setWindowTitle(appName + appVersion)
        self.setupUi()
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.resize(self.getPreferredWindowSize())

    def getPreferredWindowSize(self) -> QtCore.QSize:
        # Defaults, untested but that should fit 800x600 screens
        # Let's hope no one is using that or even lower in 2022+
        size = QtCore.QSize(600, 520)

        #Fetch the screen resolution
        qsize = QtWidgets.QApplication.primaryScreen().size()
        if qsize.width() > 1040: # Probably a 1280 or higher width resolution
            #at 1280 it still leaves 260px for a vertical taskbar
            size.setWidth(1040)
        
        #Leaves plenty of space for horizontal taskbars and hopefully docks
        if qsize.height() >= 720:
            size.setHeight(690)

        #Ideal size to fit the UI without causing scrollbars to appear
        if qsize.height() >= 1040:
            size.setHeight(990)

        return size

    def setupUi(self):
        self.keyboardQ = KeyboardQ.KeyboardQ()
        self.gLayoutMain = QtWidgets.QGridLayout(self)
        self.gLayoutMain.setMargin(0)

        self.toolBox = QtWidgets.QToolBox(self)
        self.mainP1 = QtWidgets.QWidget()
        self.toolBox.addItem(self.mainP1, "⌨ Keyboard data")
        self.gLayoutP1 = QtWidgets.QGridLayout(self.mainP1)
        
        spacerBelow = QtWidgets.QSpacerItem(5, 0, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)

        self.graphicsView = QtWidgets.QGraphicsView(self)
        self.graphicsView.setRenderHint(QtGui.QPainter.Antialiasing)

        self.svgPlateThickness = SvgPlateThickness.SvgPlateThickness()
        self.qsvgPlateThickness = QtSvg.QSvgWidget()
        self.qsvgPlateThickness.setSizePolicy(
            QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.MinimumExpanding)
        self.qsvgPlateThickness.hide() # Although empty and invisible gets in the way of mouse events if not hidden.

        self.vLayoutLeft = QtWidgets.QVBoxLayout(self.mainP1)
        self.__createGbPlate()
        self.vLayoutLeft.addWidget(self.gbPlate, 0)
        self.__createGbPadding()
        self.vLayoutLeft.addWidget(self.gbPadding, 0)
        self.__createGbCutout()
        self.vLayoutLeft.addWidget(self.gbCutout, 0)

        self.__createGbKle()
        self.gLayoutP1.addWidget(self.gbKle, 0, 0, 1, 2)
        #self.gLayoutP1.addItem(spacerAbove, 1, 1, 1, 1)
        self.gLayoutP1.addItem(self.vLayoutLeft, 3, 0, 1, 1)
        self.gLayoutP1.addWidget(self.graphicsView, 2, 1, 5, 1)
        self.gLayoutP1.addWidget(self.qsvgPlateThickness, 2, 1, 5, 1)
        self.gLayoutP1.addItem(spacerBelow, 3, 0, 1, 1)

        self.gLayoutP1.setColumnStretch(0, 0)
        self.gLayoutP1.setRowStretch(1, 1)

        self.gLayoutP1.setRowStretch(4, 1)

        self.gLayoutMain.addWidget(self.toolBox, 0, 0, 1, 1)
        self.__addStatusBarUi()
        self.gLayoutMain.addWidget(self.sts, 1, 0, 1, 1)
        self.__addOkCancelUi()
        self.gLayoutMain.addLayout(self.hLayoutOkCancel, 2, 0, 1, 1)
        self.__addSettingsPageUi()
        self.__addHelpPageUi()

        self.toolBox.setCurrentIndex(0)

        QtCore.QMetaObject.connectSlotsByName(self)

        # FIXME. A timer shouldn't be needed to get the QImageView to size 
        # properly
        timer = QtCore.QTimer()
        timer.singleShot(200, self.reloadScene)
        #self.reloadScene()

    def __addSettingsPageUi(self):
        self.mainP2 = QtWidgets.QWidget()
        self.toolBox.addItem(self.mainP2, '🔧 Settings ')
        self.gLayoutSettings = QtWidgets.QGridLayout(self)
        self.mainP2.setLayout(self.gLayoutSettings)

        self.lblSettingsCurrentValue = QtWidgets.QLabel('Current Value', self.mainP2)
        self.gLayoutSettings.addWidget(self.lblSettingsCurrentValue, 0, 1, 1, 1)
        self.lblSettingsDefaultValue = QtWidgets.QLabel('Default Value<br/>Click to restore', self.mainP2)
        self.gLayoutSettings.addWidget(
            self.lblSettingsDefaultValue, 0, 2, 1, 1)

        self.lblCloneCap = QtWidgets.QLabel('Clone cap', self.mainP2)
        self.gLayoutSettings.addWidget(self.lblCloneCap, 1, 0, 1, 1)
        self.sbCloneCap = QtWidgets.QSpinBox(self.mainP2)
        self.sbCloneCap.setMinimum(1)
        self.sbCloneCap.setMaximum(999)
        self.sbCloneCap.setValue(SETTINGS.value('CloneCap', KeyboardQ.KeyboardQ.cloneCap))
        self.sbCloneCap.valueChanged.connect(
            lambda: SETTINGS.setValue('CloneCap', self.sbCloneCap.value()))
        self.gLayoutSettings.addWidget(self.sbCloneCap, 1, 1, 1, 1)
        self.pbDefaultCloneCap = QtWidgets.QPushButton(
            str(KeyboardQ.KeyboardQ.cloneCap), self.mainP2)
        self.gLayoutSettings.addWidget(self.pbDefaultCloneCap, 1, 2, 1, 1)

        self.lblCloneCapDesc = QtWidgets.QLabel('''<html>
Every combination of key size, angle and whether the stabilizer is flipped or not leads 
to a unique footprint that is represented by a sketch, these sketches are extruded and cloned.

To create the cutouts there are two options: <ol>
<li>Create a clone of the extrude and position it where its needed</li>
<li>Create a sketch using Part.Point for the positions and use the point array to place it in all the needed positions</li></ol>
<strong>The clone cap number represent how many clones can be made and positioned before a Point Array (and Point Sketch) is used.</strong>
        </html>''')
        self.lblCloneCapDesc.setWordWrap(True)
        self.gLayoutSettings.addWidget(self.lblCloneCapDesc, 2, 0, 1, 1)

        labelsAndSettings = { 
            'Key cap color': 'KeyCapColor',
            'Key cap side color': 'KeyCapSideColor',
            'Keyboard plate color': 'KeyboardPlateColor',
            'Hover color': 'HoverColor'
        }

        for i, (label, setting) in enumerate(labelsAndSettings.items(), start=3):
            showAlpha = setting == 'HoverColor'
            lbl = QtWidgets.QLabel(label, self.mainP2)
            self.gLayoutSettings.addWidget(lbl, i, 0, 1, 1)
            cpb = ColorPickerButton(setting, self.mainP2, showAlpha)
            cpb.colorChanged.connect(lambda: self.__reloadScenes())
            self.gLayoutSettings.addWidget(cpb, i, 1, 1, 1)

            cd = ColorDefaultButton(setting, self.mainP2, showAlpha)
            cd.clicked.connect(lambda: (
                self.__reloadScenes(), self.__reloadSettingsValues(), cpb.reload()
            ))
            self.gLayoutSettings.addWidget(cd, i, 2, 1, 1)

            setattr(self, 'cpb'+setting, cpb)
        
        self.lblSettingsJSON5 = QtWidgets.QLabel('''<html>
<p>If you're looking to customize the colors used in the JSON input field, 
please do so in the main window under <div><code>Edit > Preferences > Editor</code>.</div>
"Text", "Keyword" and "String" are the colors you'll want to modify</p>
            </html>''',
            self.mainP2
        )
        self.lblSettingsJSON5.setWordWrap(True)
        self.gLayoutSettings.addWidget(self.lblSettingsJSON5, 8, 0, 1, 1)

        self.gvSettingsPreview = ResizableGraphicsView(self.mainP2)
        self.gvSettingsPreview.setRenderHint(QtGui.QPainter.Antialiasing)
        self.gvSettingsPreview.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.gLayoutSettings.addWidget(self.gvSettingsPreview, 9, 0, 1, 3)
        self.reloadSettingsPreview()

        self.pbResetSettings = QtWidgets.QPushButton('Reset', self.mainP2)
        self.gLayoutSettings.addWidget(self.pbResetSettings, 10, 0, 1, 3)
        self.pbResetSettings.clicked.connect(lambda:(
            SETTINGS.clear(), self.__reloadScenes(), self.__reloadSettingsValues(),
        ))

        self.gLayoutSettings.setColumnStretch(0, 1)
        self.gLayoutSettings.setColumnStretch(1, 0)

        self.lblSettings = QtWidgets.QLabel('''
Settings are automatically and immediately saved to %AppData%/Roaming/FreeCAD/Keyboard Generator.ini
        ''', self.mainP2)
        self.gLayoutSettings.addWidget(self.lblSettings, self.gLayoutSettings.rowCount()+2, 0, 1, 2)

    def __reloadScenes(self):
        self.reloadScene()
        self.reloadSettingsPreview()

    def reloadSettingsPreview(self):
        parsedKb = serial.parse(r'[[{a:7},"P","r","e","v","i","e","w"]]')
        kbQ = KeyboardQ.KeyboardQ()
        pads = ['paddingTop', 'paddingBottom', 'paddingLeft', 'paddingRight']
        for pad in pads:
            setattr(kbQ, pad, 10)
        kbQ.renderArrows = False
        kbQ = self.colorKeyboardQ(kbQ)
        scene: QtWidgets.QGraphicsScene = kbQ.getScene(parsedKb)
        self.gvSettingsPreview.setScene(scene)
        self.gvSettingsPreview.fitInView(scene.sceneRect(), QtCore.Qt.KeepAspectRatio)

    def colorKeyboardQ(self, keyboardQ: KeyboardQ.KeyboardQ) -> None:
        keyboardQ.keyCapBrush        = QtGui.QBrush(GetColor('KeyCapColor'))
        keyboardQ.keyCapSideBrush    = QtGui.QBrush(GetColor('KeyCapSideColor'))
        keyboardQ.keyboardPlateBrush = QtGui.QBrush(GetColor('KeyboardPlateColor'))
        keyboardQ.hoverBrush         = QtGui.QBrush(GetColor('HoverColor'))
        return keyboardQ

    def __addHelpPageUi(self):
        self.mainP3 = QtWidgets.QWidget()
        self.vLayoutP3 = QtWidgets.QVBoxLayout(self)
        self.mainP3.setLayout(self.vLayoutP3)

        self.webview = QtWebEngineWidgets.QWebEngineView()
        filename = cmdFolder + os.path.sep + 'keyboard-info.html'
        self.webview.load(QtCore.QUrl.fromLocalFile(filename))
        self.vLayoutP3.addWidget(self.webview)
        self.toolBox.addItem(self.mainP3, "❓ Supplemental Information/Credits")
        self.toolBox.setStyleSheet("padding: 0; margin: 0;")

        self.vLayoutP3.setStretch(0, 1)
        self.vLayoutP3.setStretch(1, 0)

    def __createGbKle(self):
        self.gbKle = QtWidgets.QGroupBox(self.mainP1)
        self.gbKle.setTitle("Keyboard-layout-editor.com (Click for keyboard view)")
        self.gbKle.setObjectName("gbKle")
        self.gLayoutKle = QtWidgets.QGridLayout(self.gbKle)
        self.gLayoutKle.setObjectName("gLayoutKle")

        self.txtKeyboardLayout = KeyboardCodeEditor(self.gbKle)
        self.txtKeyboardLayout.setObjectName("txtKeyboardLayout")
        self.txtKeyboardLayout.setPlainText(self.getUserKleJSON())
        self.txtKeyboardLayout.textChanged.connect(lambda: self.reloadScene())
        self.txtKeyboardLayout.focusChanged.connect(lambda: self.reloadScene())
        height = self.txtKeyboardLayout.fontMetrics().height() * (6 + 2)
        self.txtKeyboardLayout.setFixedHeight(height)
        self.txtKeyboardLayout.setStyleSheet('margin-bottom: 0;')
        self.gLayoutKle.addWidget(self.txtKeyboardLayout, 0, 0, 1, 1)
        self.gLayoutKle.setVerticalSpacing(0)

        frKleFooter = QtWidgets.QFrame(self.gbKle)
        frKleFooter.setFrameStyle(QtWidgets.QFrame.WinPanel)
        frKleFooter.setFrameShape(QtWidgets.QFrame.Panel)
        frKleFooter.setLineWidth(1)
        frKleFooter.setMidLineWidth(1)
        frKleFooter.setGeometry(0, 0, 500, 140)
        frKleFooter.setStyleSheet('padding: 0px 3px 6px 3px; margin: 0; margin-top: -1px;')
        hLayoutKleTextFooter = QtWidgets.QHBoxLayout()
        frKleFooter.setLayout(hLayoutKleTextFooter)
        lblKleFooter = QtWidgets.QLabel(frKleFooter)
        lblKleFooter.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.MinimumExpanding)
        lblKleFooter.setStyleSheet('min-width: 700;')
        lblKleFooter.setMinimumWidth(0)
        lblKleFooter.setText(
            "Use <a href=\"http://www.keyboard-layout-editor.com/\">keyboard-layout-editor.com</a> "
            "and copy/paste the \"</>Raw data\" tab/field content into the textbox above."
        )
        lblKleFooter.setWordWrap(True)
        self.gLayoutKle.addWidget(frKleFooter, 1, 0, 1, 1)

        self.helpKle = SVGPushHelpButton(self, 'keyboard-layout-editor', self.gbKle)
        self.gLayoutKle.addWidget(self.helpKle, 0, 1, 1, 1)

        self.pbResetKle = QtWidgets.QPushButton('⟲', self.gbKle)
        self.pbResetKle.setToolTip(
            'Reset the KLE field to the default keyboard layout (the letters KG)'
        )
        self.pbResetKle.clicked.connect(
            lambda: self.txtKeyboardLayout.setPlainText(self.defaultKeyboardLayout))
        self.gLayoutKle.addWidget(self.pbResetKle, 1, 1, 1, 1)

    def __createGbPlate(self):
        self.gbPlate = QtWidgets.QGroupBox(self.mainP1)
        self.gbPlate.setTitle("Plate")
        self.gLayoutPlate = QtWidgets.QGridLayout(self.mainP1)
        self.gbPlate.setLayout(self.gLayoutPlate)
        
        self.lblKbCornerStyle = QtWidgets.QLabel(self.gbPlate)
        self.lblKbCornerStyle.setText("Corner style")
        self.lblKbCornerStyle.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Minimum)
        self.lblKbCornerStyle.setToolTip("Determines the style of the plates corners. Angled, rounded or in case of a 0 (zero) value just a right angle")
        self.gLayoutPlate.addWidget(self.lblKbCornerStyle, 0, 0, 1, 1)

        self.cbKbCornerStyle = CornerTypeComboBox(self.gbPlate, Corner.NONE)
        self.gLayoutPlate.addWidget(self.cbKbCornerStyle, 0, 1, 1, 2)
        self.cbKbCornerStyle.currentIndexChanged.connect(lambda: self.__mainCornerStyleChanged())

        self.helpKeyboardCorner = SVGPushHelpButton(self, 'plate-corner-style', self.gbPlate)
        self.gLayoutPlate.addWidget(self.helpKeyboardCorner, 0, 3, 1, 1)

        # Corner Radius X-Y buttons
        self.lblKbCornerRadius = QtWidgets.QLabel(self.gbPlate)
        self.lblKbCornerRadius.setObjectName("lblPlateCornerRadius")
        self.lblKbCornerRadius.setText("Corner radius")
        self.lblKbCornerRadius.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Minimum)
        self.gLayoutPlate.addWidget(self.lblKbCornerRadius, 1, 0, 1, 1)

        self.btnXyLinked = QtWidgets.QRadioButton('S&ingle', self.gbPlate)
        self.btnXyLinked.setCheckable(True)
        self.btnXyLinked.setChecked(True)
        self.gLayoutPlate.addWidget(self.btnXyLinked, 1, 1, 1, 1)

        self.btnXyUnlinked = QtWidgets.QRadioButton('Separate (X&&&Y)', self.gbPlate)
        self.btnXyUnlinked.setCheckable(True)
        self.gLayoutPlate.addWidget(self.btnXyUnlinked, 1, 2, 1, 1)

        self.helpPlateCornerRadius = SVGPushHelpButton(self, 'plate-corner-radius', self.gbPlate)
        self.gLayoutPlate.addWidget(self.helpPlateCornerRadius, 1, 3, 2, 1)

        self.bgXy = QtWidgets.QButtonGroup()
        self.bgXy.addButton(self.btnXyLinked)
        self.bgXy.addButton(self.btnXyUnlinked)
        self.bgXy.buttonClicked.connect(self.radiusXyChanged)

        # Corner Radius 
        self.dbsKbCornerRadiusX = FocusDoubleSpinBox(self.gbPlate)
        self.dbsKbCornerRadiusX.setSingleStep(0.05)
        self.dbsKbCornerRadiusX.setMinimum(0)
        self.dbsKbCornerRadiusX.setSuffix('mm')
        self.dbsKbCornerRadiusX.setValue(self.keyboardQ.topLeft.radiusX)
        self.dbsKbCornerRadiusX.setPrefix('XY ')
        self.gLayoutPlate.addWidget(self.dbsKbCornerRadiusX, 2, 1, 1, 2)

        self.dbsKbCornerRadiusY = FocusDoubleSpinBox()
        self.dbsKbCornerRadiusY.setSingleStep(0.05)
        self.dbsKbCornerRadiusY.setMinimum(0)
        self.dbsKbCornerRadiusY.setSuffix('mm')
        self.dbsKbCornerRadiusY.setPrefix('Y ')
        self.dbsKbCornerRadiusY.setValue(self.keyboardQ.topLeft.radiusY)
        
        self.dbsKbCornerRadiusX.valueChanged.connect(lambda: self.__updateCornerRadiiAndRepaintScene())
        self.dbsKbCornerRadiusY.valueChanged.connect(lambda: self.__updateCornerRadiiAndRepaintScene())

        self.__addPerCornerUi()

        # Plate thickness
        self.lblPlateThickness = QtWidgets.QLabel("Plate thickness", self.gbPlate)
        self.lblPlateThickness.setObjectName("lblPlateThickness")
        self.lblPlateThickness.setToolTip("The thickness per Cherry's spec is 1.5m (±0.1mm)")
        self.gLayoutPlate.addWidget(self.lblPlateThickness, 4, 0, 1, 1)

        self.dbsPlateThickness = FocusDoubleSpinBox(self.gbPlate)
        self.dbsPlateThickness.focusInSignal.connect(self.showPlateThickness)
        self.dbsPlateThickness.focusOutSignal.connect(self.showDefault)
        self.dbsPlateThickness.setSingleStep(0.05)
        self.dbsPlateThickness.setProperty("value", 1.5)
        self.dbsPlateThickness.setObjectName("dbsPlateThickness")
        self.dbsPlateThickness.setSuffix('mm')
        self.dbsPlateThickness.setMinimum(0.25)
        self.dbsPlateThickness.valueChanged.connect(lambda: self.showPlateThickness())
        self.gLayoutPlate.addWidget(self.dbsPlateThickness, 4, 1, 1, 2)

        self.helpPlateThickness = SVGPushHelpButton(self, 'plate-thickness', self.gbPlate)
        self.gLayoutPlate.addWidget(self.helpPlateThickness, 4, 3, 1, 1)


        # TODO: Make this work in a sensible way.
        self.lblPlateStyle = QtWidgets.QLabel('Plate style')
        #self.gLayoutPlate.addWidget(self.lblPlateStyle, 5, 0, 1, 1)

        self.cbPlateShape = QtWidgets.QComboBox()
        for kbShape in KeyboardQ.KbShape:
            self.cbPlateShape.addItem(kbShape.value, kbShape)
        self.cbPlateShape.currentIndexChanged.connect(lambda: self.reloadScene())
        #self.gLayoutPlate.addWidget(self.cbPlateShape, 5, 1, 1, 2)
        

        #self.helpPlate

    def radiusXyChanged(self):
        if self.btnXyLinked == self.bgXy.checkedButton():
            self.showOneRadius()
        else:
            self.showXyRadii()
        self.__showHideRadii()

    def showOneRadius(self):
        self.dbsKbCornerRadiusX.setPrefix('XY ')
        self.dbsKbCornerRadiusY.hide()
        #FreeCAD.Console.PrintMessage(f'\ndbsKbCornerRadiusY.hide')
        self.gLayoutPlate.addWidget(self.dbsKbCornerRadiusX, 2, 1, 1, 2)

        for corner in Corner.Corners():
            dbsX: FocusDoubleSpinBox = self.getCornerSpinBox(corner, 'X')
            dbsX.setPrefix('XY ')
            dbsY: FocusDoubleSpinBox = self.getCornerSpinBox(corner, 'Y')
            dbsY.hide()

            gridLayout: QtWidgets.QGridLayout = dbsX.parentWidget().layout()
            layoutId = gridLayout.indexOf(dbsX)
            tuplePositionInfo = gridLayout.getItemPosition(layoutId)
            row, col = tuplePositionInfo[0], tuplePositionInfo[1]
            gridLayout.addWidget(dbsX, row, col, 1, 2)

    def showXyRadii(self):
        self.dbsKbCornerRadiusX.setPrefix('X ')
        self.gLayoutPlate.addWidget(self.dbsKbCornerRadiusX, 2, 1, 1, 1)
        self.dbsKbCornerRadiusY.show()
        self.gLayoutPlate.addWidget(self.dbsKbCornerRadiusY, 2, 2, 1, 1)

        for corner in Corner.Corners():
            dbsX = self.getCornerSpinBox(corner, 'X')
            dbsX.setPrefix('X ')

            gridLayout: QtWidgets.QGridLayout = dbsX.parentWidget().layout()
            layoutId = gridLayout.indexOf(dbsX)
            tuplePositionInfo = gridLayout.getItemPosition(layoutId)
            row, col = tuplePositionInfo[0], tuplePositionInfo[1]
            gridLayout.addWidget(dbsX, row, col, 1, 1)
            dbsY = self.getCornerSpinBox(corner, 'Y')
            gridLayout.addWidget(dbsY, row, col+1, 1, 1)
            dbsY.setVisible(self.gbPerCorner.isChecked())


    def __showHideRadii(self):
        showY = self.btnXyUnlinked.isChecked()
        showRadiusX = self.cbKbCornerStyle.currentData() != KeyboardQ.CornerStyle.RIGHT
        showRadiusY = showRadiusX and showY
        self.dbsKbCornerRadiusX.setVisible(showRadiusX)
        self.dbsKbCornerRadiusY.setVisible(showRadiusY)

        showCornerRadiusRow = False

        for corner in KeyboardQ.Corner.Corners():
            isNotRightAngle = self.getCornerComboBox(corner).currentData() != KeyboardQ.CornerStyle.RIGHT
            showCorners = self.gbPerCorner.isChecked()
            showPerCornerRadiusX = isNotRightAngle and showCorners
            showPerCornerRadiusY = isNotRightAngle and showY and showCorners
            self.getCornerSpinBox(corner, 'X').setVisible(showPerCornerRadiusX)
            self.getCornerSpinBox(corner, 'Y').setVisible(showPerCornerRadiusY)
            
            if isNotRightAngle:
                showCornerRadiusRow = True

        # Hide entire radius row?
        cornerRadiusRowWidgets = [self.lblKbCornerRadius, self.btnXyLinked, 
            self.btnXyUnlinked, self.dbsKbCornerRadiusX, self.dbsKbCornerRadiusY]
        for cornerRadiusRowWidget in cornerRadiusRowWidgets:
            showThisElement = showCornerRadiusRow
            if cornerRadiusRowWidget == self.dbsKbCornerRadiusY and not showY:
                showThisElement = False
            cornerRadiusRowWidget.setVisible(showThisElement)
            
    def getCornerSpinBox(self, corner: Corner, xOrY = 'X') -> FocusDoubleSpinBox:
        return getattr(self, corner.ToVarName('dbsKbCorner{}'+xOrY))
    
    def getCornerComboBox(self, corner: Corner) -> CornerTypeComboBox:
        return getattr(self, corner.ToVarName('cbKbCorner{}'))

    def __addPerCornerUi(self):
        self.gbPerCorner = CollapsibleGroupBox(self.gbPlate)
        self.gbPerCorner.setTitle("Style/Radius p&er corner")
        self.gbPerCorner.setFlat(True)
        # Disables / enabled global controls, note that things inside the groupbox
        # already automatically get hidden/shown because it's a CollapsibleGroupBox
        self.gbPerCorner.clicked.connect(lambda: self.toggleUniversalCornerStyle())
        self.gbPerCorner.clicked.connect(self.__showHideRadii)
        self.gLayoutPerCorner = QtWidgets.QGridLayout(self.gbPerCorner)

        horizontalLine = QtWidgets.QFrame(self.gbPerCorner)
        horizontalLine.setFrameStyle(QtWidgets.QFrame.HLine | QtWidgets.QFrame.Sunken)
        self.gLayoutPerCorner.addWidget(horizontalLine, 2, 0, 1, 9)

        self.__createCornerUi(Corner.TOPLEFT, row=0, col=0)
        self.__createCornerUi(Corner.TOPRIGHT, row=0, col=5)
        self.__createCornerUi(Corner.BOTTOMLEFT, row=3, col=0)
        self.__createCornerUi(Corner.BOTTOMRIGHT, row=3, col=5)


        self.gLayoutPerCorner.setColumnStretch(0, 0)
        self.gLayoutPerCorner.setColumnStretch(1, 0)
        self.gLayoutPerCorner.setColumnStretch(2, 0)
        self.gLayoutPerCorner.setColumnStretch(3, 1)
        self.gLayoutPerCorner.setColumnStretch(4, 0)
        self.gLayoutPerCorner.setColumnStretch(5, 0)
        self.gLayoutPerCorner.setColumnStretch(6, 0)
        self.gbPerCorner.showItems(False)
        self.gLayoutPlate.addWidget(self.gbPerCorner, 3, 0, 1, 4)

    def __createCornerUi(self, corner: Corner, row: int, col: int):
        varNamePart = corner.ToVarName('KbCorner{}')
        # The base themes set min-width to 50px on QSpinBox to reserve space for a suffix
        # If no suffix is used the QSpinBox ends up wider than it needs to be.
        negateSuffixSpacing = 'min-width: 20px; padding-right: 5px'

        cb = CornerTypeComboBox(self.gbPerCorner, corner)
        cb.currentIndexChanged.connect(lambda: self.reloadScene())
        cb.currentIndexChanged.connect(lambda: self.__showHideRadii())
        setattr(self, 'cb'+varNamePart, cb)
        self.gLayoutPerCorner.addWidget(cb, row, col, 1, 2)

        dbsX = FocusDoubleSpinBox(self.gbPerCorner)
        dbsX.setValue(self.dbsKbCornerRadiusX.value())
        dbsX.setSingleStep(0.05)
        dbsX.valueChanged.connect(lambda: self.reloadScene())
        dbsX.setPrefix('X ')
        dbsX.setStyleSheet(negateSuffixSpacing)
        self.gLayoutPerCorner.addWidget(dbsX, row+1, col, 1, 2)
        setattr(self, 'dbs'+varNamePart+'X', dbsX)

        dbsY = FocusDoubleSpinBox()
        dbsY.setValue(self.dbsKbCornerRadiusY.value())
        dbsY.setSingleStep(0.05)
        dbsY.valueChanged.connect(lambda: self.reloadScene())
        dbsY.setPrefix('Y ')
        dbsY.setStyleSheet(negateSuffixSpacing)
        #self.gLayoutPerCorner.addWidget(dbsY, row+1, col+1, 1, 1)
        setattr(self, 'dbs'+varNamePart+'Y', dbsY)

    def toggleUniversalPadding(self):
        self.dbsPadding.setEnabled(not self.gbPaddingPerSide.isChecked())
        self.lblPadding.setEnabled(not self.gbPaddingPerSide.isChecked())
        self.reloadScene()

    def __mainCornerStyleChanged(self):
        self.__matchPerCornerStyleToMainControl()
        self.__showHideRadii()


    def __matchPerCornerStyleToMainControl(self):
        for corner in Corner.Corners():
            self.getCornerComboBox(corner).setCurrentIndex(
                self.cbKbCornerStyle.currentIndex()
            )
            self.reloadScene()

    def toggleUniversalCornerStyle(self):
        universalCornerWidgets = [
            self.dbsKbCornerRadiusX, self.dbsKbCornerRadiusY, 
            self.cbKbCornerStyle, self.lblKbCornerStyle
        ]

        cursor = QtGui.QCursor(QtCore.Qt.ArrowCursor)
        if self.gbPerCorner.isChecked():
            cursor = QtGui.QCursor(QtCore.Qt.ForbiddenCursor)

        widget: QtWidgets.QWidget
        for widget in universalCornerWidgets:
            widget.setCursor(cursor)
            widget.setEnabled(not self.gbPerCorner.isChecked())

        self.reloadScene()

    def __updateCornerRadiiAndRepaintScene(self):

        if self.bgXy.checkedButton() == self.btnXyLinked:
            self.dbsKbCornerRadiusY.setValue(self.dbsKbCornerRadiusX.value())

        for corner in Corner.Corners():
            dbsX = self.getCornerSpinBox(corner, 'X')
            dbsY = self.getCornerSpinBox(corner, 'Y')
            dbsX.setValue(self.dbsKbCornerRadiusX.value())
            dbsY.setValue(self.dbsKbCornerRadiusY.value())

        self.reloadScene()

    def __updateSidePaddingsAndReloadScene(self):
        for side in KeyboardQ.Padding.Sides():
            self.getPaddingSpinBox(side).setValue(self.dbsPadding.value())
        self.reloadScene()

    def getPaddingSpinBox(self, side: KeyboardQ.Padding) -> PaddingDoubleSpinBox:
        return getattr(self, side.ToVarName('dbsPadding{}'))

    def __createGbPadding(self):
        self.gbPadding = QtWidgets.QGroupBox(self.mainP1)
        self.gbPadding.setObjectName("gbPadding")
        self.gbPadding.setTitle("Padding")

        #Add layout
        self.gLayout_Padding = QtWidgets.QGridLayout(self.gbPadding)
        self.gLayout_Padding.setObjectName("gLayout_Padding")

        self.bgPadFrom = QtWidgets.QButtonGroup()
        self.bgPadFrom.buttonClicked.connect(lambda: self.reloadScene())

        self.lblPadFrom = QtWidgets.QLabel("Pad from", self.gbPadding)
        self.gLayout_Padding.addWidget(self.lblPadFrom, 0, 0, 1, 1)
        self.pbPadFromReserved = QtWidgets.QRadioButton("Reser&ved", self.gbPadding)
        self.bgPadFrom.addButton(self.pbPadFromReserved)
        self.pbPadFromReserved.setCheckable(True)
        self.pbPadFromReserved.setChecked(True)
        self.gLayout_Padding.addWidget(self.pbPadFromReserved, 0, 1, 1, 1)
        self.pbPadFromSwitch = QtWidgets.QRadioButton("Cu&tout", self.gbPadding)
        self.bgPadFrom.addButton(self.pbPadFromSwitch)
        self.pbPadFromSwitch.setCheckable(True)
        self.gLayout_Padding.addWidget(self.pbPadFromSwitch, 0, 2, 1, 1)

        self.helpPadFrom = SVGPushHelpButton(self, 'pad-from')
        self.gLayout_Padding.addWidget(self.helpPadFrom, 0, 3, 1, 1)
        
        self.lblPadding = QtWidgets.QLabel("Pad all by", self.gbPadding)
        self.lblPadding.setToolTip(
            "Sets the padding on all sides in one go, enable padding per side if you want to set this for each side separately")
        self.gLayout_Padding.addWidget(self.lblPadding, 1, 0, 1, 1)

        self.dbsPadding = PaddingDoubleSpinBox(self.gbPadding, KeyboardQ.Padding.ALL, self)
        self.dbsPadding.setObjectName("dbsPadding")        
        self.dbsPadding.valueChanged.connect(lambda: self.__updateSidePaddingsAndReloadScene())
        self.gLayout_Padding.addWidget(self.dbsPadding, 1, 1, 1, 2)

        self.helpPadding = SVGPushHelpButton(self, 'pad-all-by', self.mainP1)
        self.gLayout_Padding.addWidget(self.helpPadding, 1, 3, 1, 1)

        # Sub groupbox
        self.gbPaddingPerSide = CollapsibleGroupBox(self.gbPadding)
        self.gbPaddingPerSide.setObjectName("gbPaddingPerSide")
        self.gbPaddingPerSide.setTitle("Padding per &side")
        self.gbPaddingPerSide.setToolTip("Enable the fields below to set the padding for each side separately")
        self.gbPaddingPerSide.setCheckable(True)
        self.gbPaddingPerSide.setChecked(False)
        self.gbPaddingPerSide.setFlat(True)        
        QtCore.QObject.connect(self.gbPaddingPerSide, QtCore.SIGNAL("clicked()"), self.toggleUniversalPadding)
        self.gLayout_Padding.addWidget(self.gbPaddingPerSide, 2, 0, 1, 4)

        self.gLayoutPaddingPerSide = QtWidgets.QGridLayout(self.gbPaddingPerSide)

        self.lblPaddingTop = QtWidgets.QLabel("Top", self.gbPaddingPerSide)
        self.lblPaddingTop.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.gLayoutPaddingPerSide.addWidget(self.lblPaddingTop, 0, 1, 1, 1)
        self.dbsPaddingTop = PaddingDoubleSpinBox(self.gbPaddingPerSide, KeyboardQ.Padding.TOP, self)
        self.gLayoutPaddingPerSide.addWidget(self.dbsPaddingTop, 0, 2, 1, 1)
        
        self.lblPaddingLeft = QtWidgets.QLabel("Left", self.gbPaddingPerSide)
        self.lblPaddingLeft.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.gLayoutPaddingPerSide.addWidget(self.lblPaddingLeft, 1, 0, 1, 1)
        self.dbsPaddingLeft = PaddingDoubleSpinBox(self.gbPaddingPerSide, KeyboardQ.Padding.LEFT, self)
        self.gLayoutPaddingPerSide.addWidget(self.dbsPaddingLeft, 1, 1, 1, 1)
        
        self.lblPaddingRight = QtWidgets.QLabel("Right", self.gbPaddingPerSide)
        self.lblPaddingRight.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.gLayoutPaddingPerSide.addWidget(self.lblPaddingRight, 1, 2, 1, 1)
        self.dbsPaddingRight = PaddingDoubleSpinBox(self.gbPaddingPerSide, KeyboardQ.Padding.RIGHT, self)
        self.gLayoutPaddingPerSide.addWidget(self.dbsPaddingRight, 1, 3, 1, 1)

        self.lblPaddingBottom = QtWidgets.QLabel("Bottom", self.gbPaddingPerSide)
        self.lblPaddingBottom.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.gLayoutPaddingPerSide.addWidget(self.lblPaddingBottom, 2, 1, 1, 1)
        self.dbsPaddingBottom = PaddingDoubleSpinBox(self.gbPaddingPerSide, KeyboardQ.Padding.BOTTOM, self)
        self.gLayoutPaddingPerSide.addWidget(self.dbsPaddingBottom, 2, 2, 1, 1)

        self.gbPaddingPerSide.showItems(False)
    
    def highlightPreview(self, side: KeyboardQ.Padding):
        self.paddingToHighlight = side
        self.reloadScene()

    def unHighlightPreview(self, side: KeyboardQ.Padding):
        self.paddingToHighlight = KeyboardQ.Padding.NONE
        self.reloadScene()

    def showPlateThickness(self):
        self.svgPlateThickness.plateHeight = round(self.dbsPlateThickness.value(), 2)

        renderer = self.qsvgPlateThickness.renderer()
        renderer.load(self.svgPlateThickness.getByteArray())
        renderer.setAspectRatioMode(QtCore.Qt.KeepAspectRatio)
        self.graphicsView.hide()
        self.qsvgPlateThickness.show()

    def showDefault(self):
        self.graphicsView.show()
        self.qsvgPlateThickness.hide()

    def __createGbCutout(self):
        self.gbCutout = QtWidgets.QGroupBox(self.mainP1)
        self.gbCutout.setTitle("Cutouts")
        self.gLayoutCutout = QtWidgets.QGridLayout(self.gbCutout)
        self.gbCutout.setLayout(self.gLayoutCutout)

        # Switch
        self.__createSubGbSwitch()
        self.__createSubGbStab()
        
        self.cbSwitch.currentIndexChanged.connect(lambda: self.cbStab.reCreateList(
            self.cbSwitch.currentData()
        ))
        self.cbSwitch.currentIndexChanged.connect(lambda: self.reloadScene())
        #Kerf
        self.lblKerf = QtWidgets.QLabel('Kerf', self.gbCutout)
        self.lblKerf.setToolTip('Kerf is the width of the material removed by the cutting tool')
        self.gLayoutCutout.addWidget(self.lblKerf, 3, 0, 1, 3)

        self.dsbKerf = QtWidgets.QDoubleSpinBox(self.gbCutout)
        self.dsbKerf.setSuffix('mm')
        self.dsbKerf.setSingleStep(0.05)
        self.dsbKerf.setValue(0)
        self.dsbKerf.setMinimum(-1)
        self.dsbKerf.setMaximum(1)
        self.dsbKerf.valueChanged.connect(lambda: self.reloadScene())        
        self.gLayoutCutout.addWidget(self.dsbKerf, 3, 3, 1, 1)

        self.helpKerf = SVGPushHelpButton(self, 'cutout-kerf', self.gbCutout)
        self.gLayoutCutout.addWidget(self.helpKerf, 3, 4, 1, 1)
        
        self.lblCutoutSpacing = QtWidgets.QLabel('Spacing', self.gbCutout)
        self.gLayoutCutout.addWidget(self.lblCutoutSpacing, 4, 0, 1, 2)

        self.cbCutoutSpacing = QtWidgets.QComboBox(self.gbCutout)
        self.cbCutoutSpacing.addItem('19.05mm', 19.05)
        self.cbCutoutSpacing.addItem('19.00mm', 19.00)
        self.cbCutoutSpacing.currentIndexChanged.connect(lambda: self.changeSwitchSpacing())
        self.gLayoutCutout.addWidget(self.cbCutoutSpacing, 4, 3, 1, 1)

        self.helpCutoutSpacing = SVGPushHelpButton(self, 'cutout-spacing', self.gbCutout)
        self.gLayoutCutout.addWidget(self.helpCutoutSpacing, 4, 4, 1, 1)

    def changeSwitchSpacing(self):
        Key.KeyReservedSpace.ONE_U = self.cbCutoutSpacing.currentData()
        self.reloadScene()

    def __createSubGbSwitch(self):
        self.lblSwitch = QtWidgets.QLabel(self.gbCutout)
        self.lblSwitch.setText('Switch')
        self.gLayoutCutout.addWidget(self.lblSwitch, 0, 0, 1, 1)

        self.qsvgRightMouseButton = QtSvg.QSvgWidget(svgFolder+'mouse-left-click.svg')
        lmbRenderer = self.qsvgRightMouseButton.renderer()
        lmbRenderer.setAspectRatioMode(QtCore.Qt.KeepAspectRatio)
        self.qsvgRightMouseButton.setMaximumHeight(20)
        self.gLayoutCutout.addWidget(self.qsvgRightMouseButton, 0, 1, 1, 1)

        self.pbRotateSwitchWithStab = QtWidgets.QPushButton(self.gbCutout)
        self.pbRotateSwitchWithStab.setCheckable(True)
        self.pbRotateSwitchWithStab.setChecked(False)
        self.pbRotateSwitchWithStab.setToolTip('Rotate with vertically stabilized keys')
        self.pbRotateSwitchWithStab.setText(' 90° ↻')
        self.pbRotateSwitchWithStab.clicked.connect(lambda: self.reloadScene())
        self.gLayoutCutout.addWidget(self.pbRotateSwitchWithStab, 0, 2, 1, 1)

        self.cbSwitch = KbSwitchComboBox(self.gbCutout)
        self.gLayoutCutout.addWidget(self.cbSwitch, 0, 3, 1, 1)

        self.helpSwitch = SVGPushHelpButton(self, 'cutout-switch', self.gbCutout)
        self.gLayoutCutout.addWidget(self.helpSwitch, 0, 4, 1, 1)
        

    def __createSubGbStab(self):
        # Stab
        self.lblStab = QtWidgets.QLabel(self.gbCutout)
        self.lblStab.setText('Stabilizer')
        self.lblStab.setToolTip('''The type of cutout for the stabilizer<ul>
        <li>Cherry+Costar is a hybrid that fits either (and pcb mounted) stabilizers</li>
        <li>Cherry fits just Cherry (and pcb mounted) stabilizers </li>
        <li>Costar fits only plate mounted Costar stabilizers</li>
        </ul>''')
        self.gLayoutCutout.addWidget(self.lblStab, 2, 0, 1, 1)

        self.qsvgLeftMouseButton = QtSvg.QSvgWidget(svgFolder+'mouse-right-click.svg')
        lmbRenderer = self.qsvgLeftMouseButton.renderer()
        lmbRenderer.setAspectRatioMode(QtCore.Qt.KeepAspectRatio)
        self.gLayoutCutout.addWidget(self.qsvgLeftMouseButton, 2, 1, 1, 1)
        self.qsvgLeftMouseButton.setMaximumHeight(20)

        self.pbStabFlip = QtWidgets.QPushButton(self.gbCutout)
        self.pbStabFlip.setText('180° ⮃')
        self.pbStabFlip.setCheckable(True)
        self.pbStabFlip.setToolTip("Rotates the stabilizers 180° (see the preview)")
        self.pbStabFlip.clicked.connect(lambda: self.reloadScene())
        self.gLayoutCutout.addWidget(self.pbStabFlip, 2, 2, 1, 1)
        
        self.cbStab = KbStabComboBox(self.gbCutout, self.cbSwitch.currentData())
        self.cbStab.currentIndexChanged.connect(lambda: self.reloadScene())
        self.gLayoutCutout.addWidget(self.cbStab, 2, 3, 1, 1)

        self.helpStab = SVGPushHelpButton(self, 'cutout-stab', self.gbCutout)
        self.gLayoutCutout.addWidget(self.helpStab, 2, 4, 1, 1)

    def __addOkCancelUi(self):
        self.qwOkCancel = QtWidgets.QWidget(self.sts)
        self.hLayoutOkCancel = QtWidgets.QHBoxLayout(self.qwOkCancel)

        self.pbOk = QtWidgets.QPushButton(self.sts)
        self.pbOk.setText("Ok")
        self.pbOk.setShortcut("Alt+O")
        self.pbOk.setToolTip('''<html>
        <strong>Warning: </strong> Pressing Ok might freeze FreeCAD for several seconds.
        The KeyMasterSketch seems to be the biggest holdup due to Sketcher's single threaded nature.
        </html>''')

        QtCore.QObject.connect(self.pbOk, QtCore.SIGNAL("pressed()"), self.createKeyboardSketch)
        self.hLayoutOkCancel.addWidget(self.pbOk)

        self.pbCancel = QtWidgets.QPushButton(self.sts)
        self.pbCancel.setText("Cancel")
        self.pbCancel.setShortcut("Alt+C")
        QtCore.QObject.connect(self.pbCancel, QtCore.SIGNAL("pressed()"), self.close)
        self.hLayoutOkCancel.addWidget(self.pbCancel)

        self.sts.addPermanentWidget(self.qwOkCancel)

    def __addStatusBarUi(self):
        self.sts = QtWidgets.QStatusBar(self)
        
        htmlColorTable = '''
        <table width="370"><tr>
        <th bgcolor="#506352"><font color="#fff">Green</font></th>
        <th bgcolor="#614c16"><font color="#fff">Orange</font></th>
        <th bgcolor="#614343"><font color="#fff">Red</font></th>
        <th bgcolor="#ff0000"><font color="#fff">Bright red</font></th>
        </tr><tr>
        <td>Bog standard should be easy to find</td>
        <td>Can be challenging to find</td>
        <td>Very hard to find</td>
        <td>Needs to be custom made</td>
        </tr></table>'''

        
        self.lblStabCount = QtWidgets.QLabel(self.sts)
        self.lblStabCount.setToolTip('<p>Number of stabs needed to assemble this keyboard</p>' + htmlColorTable)
        self.sts.addPermanentWidget(self.lblStabCount, 0)

        self.lblKeyCount = QtWidgets.QLabel(self.sts)
        self.lblKeyCount.setToolTip('''<p>The number and sort of keycaps you will need
        <br/>The total number is equal to the number of needed switches</p>''' + htmlColorTable)
        self.sts.addPermanentWidget(self.lblKeyCount, 0)

        self.helpStabAndKeySizes = SVGPushHelpButtonRedAlert(self, 'standard-sizes', self.sts)
        self.sts.addPermanentWidget(self.helpStabAndKeySizes)
        self.sts.setSizeGripEnabled(False)

        self.gLayoutMain.addWidget(self.sts)

    def cornerRadiusSelected(self):
        self.reloadScene()

    def cornerRadiusUnSelected(self):
        self.reloadScene()

    def cornerRadiusChanged(self):
        self.reloadScene()

    def reloadScene(self):
        self.keyboardQ = KeyboardQ.KeyboardQ()
        self.keyboardQ.switchType = self.cbSwitch.currentData()
        self.keyboardQ.stabilizerType = self.cbStab.currentData()
        self.keyboardQ.flipStabilizers = self.pbStabFlip.isChecked()
        self.keyboardQ.rotateSwitch = self.pbRotateSwitchWithStab.isChecked()
        self.keyboardQ.showKeyCap = self.txtKeyboardLayout.hasFocus()
        self.keyboardQ.kerf = self.dsbKerf.value()
        self.keyboardQ.shape = self.cbPlateShape.currentData()
        self.keyboardQ.thickness = round(self.dbsPlateThickness.value(), 2)
        self.keyboardQ.paddingBrush = self.txtKeyboardLayout.palette().highlight()

        self.keyboardQ.padFromReserved = self.bgPadFrom.checkedButton() == self.pbPadFromReserved
        self.keyboardQ.paddingToHighlight = self.paddingToHighlight

        self.keyboardQ = self.colorKeyboardQ(self.keyboardQ)

        for side in KeyboardQ.Padding.Sides():
            padVal = self.getPaddingSpinBox(side).value(
            ) if self.gbPaddingPerSide.isChecked() else self.dbsPadding.value()

            setattr(self.keyboardQ, side.ToVarName('padding{}'), padVal)

        for kbCorner in self.cornerInfo():
            setattr(self.keyboardQ, kbCorner.corner.value, kbCorner)
        
        try: 
            json5 = self.addArrayIfNeeded(self.txtKeyboardLayout.toPlainText())
            self.serialKeyboard = serial.parse(json5)
            self.helpStabAndKeySizes.cancelRedAlert()
            self.pbOk.setEnabled(True)
            self.sts.showMessage('✔️ Valid keyboard layout')
            self.saveUserKleJSON()
            
            scene: QtWidgets.QGraphicsScene = self.keyboardQ.getScene(self.serialKeyboard)
            self.graphicsView.setScene(scene)
            self.graphicsView.fitInView(scene.sceneRect(), QtCore.Qt.KeepAspectRatio)

            # After .getByteArray the keys/stabs are counted.
            ksdReport = self.keyboardQ.stabKeyDifficultyReport()
            stabReport = ksdReport.stabReport
            keyReport = ksdReport.keyReport

            self.lblStabCount.setText(self.getReportTable('Stabs:', stabReport))
            self.lblKeyCount.setText(self.getReportTable('Keys: ', keyReport))
        except json.decoder.JSONDecodeError as e:
            self.helpStabAndKeySizes.startRedAlert()
            self.pbOk.setEnabled(False)
            self.sts.showMessage('❌ The JSON couldn\'t be parsed')

    # Creates a file **NOT TO BE INCLUDED** in Keyboard-Generator.FCMacro
    # This is the 'last' keyboard the user put in
    def saveUserKleJSON(self):
        with open(self.userJSON5FilePath, 'w', encoding="utf-8") as f:
            f.write(self.txtKeyboardLayout.toPlainText())    

    def getUserKleJSON(self):
        if os.path.exists(self.userJSON5FilePath):
            with open(self.userJSON5FilePath, 'r', encoding='utf-8') as f:
                layout = f.read()
        else:
            layout = self.defaultKeyboardLayout

        return self.addArrayIfNeeded(layout)

    def cornerInfo(self) -> typing.List[KeyboardQ.KbCorner]:
        kbCorners = []

        for corner in Corner.Corners():
            if self.gbPerCorner.isChecked():
                valueX = round(self.getCornerSpinBox(corner, 'X').value(), 2)
                valueY = round(self.getCornerSpinBox(corner, 'Y').value(), 2)
            else:
                valueX = round(round(self.dbsKbCornerRadiusX.value()), 2)
                valueY = round(round(self.dbsKbCornerRadiusY.value()), 2)

            kbCorners.append(KeyboardQ.KbCorner(
                corner, valueX, valueY, self.getCornerComboBox(corner).currentData()
            ))

        return kbCorners

    def resizeEvent(self, event):
        self.graphicsView.fitInView(self.graphicsView.sceneRect(), QtCore.Qt.KeepAspectRatio)
        return super().resizeEvent(event)

    def addArrayIfNeeded(self, userInputJSON5: str):
        # The 'Raw data' field on keyboard-layout-generator.com foregoes the keyboard meta field
        # and skips the 'outer array'. Skipping this outer array means it's not valid JSON(5)
        # https://github.com/ijprest/keyboard-layout-editor/wiki/Serialized-Data-Format
        #
        # Add an entire array if there's none to fix this.
        userInputEndsOnDoubleSquareBracket = re.search(']\s*,?\s*]\s*\Z', userInputJSON5)
        if not userInputEndsOnDoubleSquareBracket:
            # Add some brackets
            userInputJSON5 = '[' + userInputJSON5 + ']'

        return userInputJSON5

    def getReportTable(self, thText: str, report: KeyboardQ.UnitDifficultyReport):
        table = '<table border="0" cellpadding="3" cellspacing="1" bgcolor="#cecece"><tr>'\
            '<th valign="middle" rowspan="2" bgcolor="#333" color="#fff">{}</th>'\
            '<th valign="middle" rowspan="2" bgcolor="#333" color="#fff">{}</th>'

        table = table.format(thText, report.totalCount)
        for unitDifficulty in report.unitCountAndDifficulties:
            table += self.getDifficultyTh(unitDifficulty)
        table += '</tr><tr>'
        for unitDifficulty in report.unitCountAndDifficulties:
            table += self.getDifficultyTd(unitDifficulty)
        table += '</tr></table>'

        return table

    def getDifficultyTh(self, udr: KeyboardQ.UnitCountAndDifficulty):
        strThTemplate = '<th bgcolor="{}" style="color: #fff">{}</th>'
        return strThTemplate.format(
            self.getColorForDifficulty(udr.difficulty),
            udr.sizeInU
        )
    
    def getDifficultyTd(self, udr: KeyboardQ.UnitCountAndDifficulty):
        strTdTemplate = '<td align="center" bgcolor="{}" style="color: #fff"><font face="monospace">{}</font></th>'
        return strTdTemplate.format(
            self.getColorForDifficulty(udr.difficulty),
            udr.count
        )

    def getColorForDifficulty(self, difficulty: Key.Difficulty):
        if difficulty == Key.Difficulty.EASY:
            return '#506352'
        elif difficulty == Key.Difficulty.MEDIUM: 
            return '#614c16'
        elif difficulty == Key.Difficulty.HARD:   
            return '#614343'
        else: # Key.Difficulty.CUSTOM
            return '#ff0000'


    def getTd(self, difficulty: Key.Difficulty, count: int, unit: str):        
        strTdTemplate = '<td bgcolor="{}" style="color: #fff">'
        if difficulty == Key.Difficulty.EASY:
            strTd = strTdTemplate.format('#506352')
        elif difficulty == Key.Difficulty.MEDIUM: 
            strTd = strTdTemplate.format('#614c16')
        elif difficulty == Key.Difficulty.HARD:   
            strTd = strTdTemplate.format('#614343')
        else:
            strTd = strTdTemplate.format('#ff0000')
        
        return (strTd + '{}x{}' + '</td>').format(str(count), unit)

    def __reloadSettingsValues(self):
        for cpb in [self.cpbKeyCapColor, self.cpbKeyCapSideColor, self.cpbKeyboardPlateColor]:
            cpb.reload()

    def luminance(self, qcolor):
        return qcolor.red() * 0.2126 + qcolor.green() * 0.7152 + qcolor.blue() * 0.0722

    def createKeyboardSketch(self):
        startTime = time.time()
        # Create clone of KeyboardQ and make it a FreeCADKeyboard
        self.freeCADKeyboard = copy.copy(self.keyboardQ)
        self.freeCADKeyboard.__class__ = FreeCADKeyboard.FreeCADKeyboard
  
        self.doc = FreeCAD.newDocument()
        self.body = self.doc.addObject('PartDesign::Body', 'KeyboardPlateBody')
        FreeCADGui.activeView().setActiveObject('pdbody', self.body)
        self.freeCADKeyboard.createSketches(self.doc,  self.body)
        self.doc.recompute(None, True, True)
        FreeCADGui.ActiveDocument.ActiveView.fitAll()
        self.close()

        endTime = time.time()
        elapsedTime = endTime - startTime
        FreeCAD.Console.PrintMessage(f"Created keyboard files in: {elapsedTime:.2f} seconds\n")

class SVGPushHelpButton(QtWidgets.QPushButton):
    def __init__(self, dialog: UiDialog, jumpTo: str, parent = None):
        super(SVGPushHelpButton, self).__init__(parent)
        self.dialog = dialog

        imgColoredQuestionMark = QtGui.QImage(iconFolder + 'questionmark.svg')
        pixmapColor = QtGui.QPixmap.fromImage(imgColoredQuestionMark)
        self.iconHelpColored = QtGui.QIcon(pixmapColor)

        imgGrayQuestionMark = self.convertToGrayScale(imgColoredQuestionMark)
        pixmapGray = QtGui.QPixmap.fromImage(imgGrayQuestionMark)
        self.iconHelpGray = QtGui.QIcon(pixmapGray)

        self.setMinimumSize(20, 20)
        self.setMaximumWidth(20)
        self.setIcon(self.iconHelpGray)
        self.setStyleSheet('border: none; background-color: transparent; padding: 0')
        self.setCursor(QtCore.Qt.PointingHandCursor)

        self.urlWithId = 'file:///'
        self.urlWithId += cmdFolder.replace('\\', '/') + '/keyboard-info.html#'+jumpTo
        self.clicked.connect(lambda: self.jumpTo())

    def jumpTo(self):
        self.dialog.toolBox.setCurrentIndex(2)
        self.dialog.webview.load(QtCore.QUrl(self.urlWithId))

    def convertToGrayScale(self, img: QtGui.QImage) -> QtGui.QImage:
        for x in range(img.width()):
            for y in range(img.height()):
                pixel = img.pixel(x, y)
                gray = QtGui.qGray(pixel)
                alpha = QtGui.qAlpha(pixel)
                img.setPixel(x, y, QtGui.qRgba(gray, gray, gray, alpha))
        return img

    def redAlert(self):
        pixmapIcon = self.icon().pixmap(100, 100)
        img = pixmapIcon.toImage()
        imgRed = self.convertToRedScale(img)
        self.iconHelpGray = QtGui.QIcon(QtGui.QPixmap.fromImage(imgRed))

    def enterEvent(self, event):
        self.setIcon(self.iconHelpColored)
        return super(SVGPushHelpButton, self).enterEvent(event)

    def leaveEvent(self, event):
        self.setIcon(self.iconHelpGray)
        return super(SVGPushHelpButton, self).leaveEvent(event)


class SVGPushHelpButtonRedAlert(SVGPushHelpButton):
    def __init__(self, dialog: UiDialog, jumpTo: str, parent = None):
        super(SVGPushHelpButtonRedAlert, self).__init__(dialog, jumpTo, parent)

        pixmapIcon = self.icon().pixmap(100, 100)
        img = pixmapIcon.toImage()
        imgRed = self.convertToRedScale(img)
        self.iconHelpRed = QtGui.QIcon(QtGui.QPixmap.fromImage(imgRed))
        self.redAlert = False

    def convertToRedScale(self, img: QtGui.QImage) -> QtGui.QImage:
        for x in range(img.width()):
            for y in range(img.height()):
                pixel = img.pixel(x, y)
                gray = QtGui.qGray(pixel)
                alpha = QtGui.qAlpha(pixel)
                img.setPixel(x, y, QtGui.qRgba(255, gray, gray, alpha))
        return img

    def startRedAlert(self):
        self.redAlert = True
        self.setIcon(self.iconHelpRed)
        self.anim = QtCore.QPropertyAnimation(self, b"pos")
        self.anim.setStartValue(self.pos() + QtCore.QPoint(-1, 0))
        self.anim.setEndValue(self.pos() + QtCore.QPoint(1, 0))
        self.anim.setEasingCurve(QtCore.QEasingCurve.InOutBounce)
        self.anim.setDuration(150)
        self.anim.setLoopCount(5)
        self.anim.start()

    def cancelRedAlert(self):
        self.redAlert = False
        self.setIcon(self.iconHelpGray)
        if hasattr(self, 'anim'):
            self.anim.stop()

    def leaveEvent(self, event):
        if self.redAlert:
            self.setIcon(self.iconHelpRed)
        else:
            self.setIcon(self.iconHelpGray)
        return super(SVGPushHelpButton, self).leaveEvent(event)


