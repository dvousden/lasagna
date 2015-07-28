#!/usr/bin/python

"""
Show coronal, transverse and saggital plots in different panels

Example usage:
threeSubPlots.py myImage.tiff myImage2.tiff
threeSubPlots.py myImage.mhd myImage2.mhd
threeSubPlots.py myImage.tiff myImage2.mhd

Depends on:
vtk
pyqtgraph (0.9.10 and above 0.9.8 is known not to work)
numpy
tifffile
argparse
tempfile
urllib
"""

__author__ = "Rob Campbell"
__license__ = "GPL v3"
__maintainer__ = "Rob Campbell"



from pyqtgraph.Qt import QtCore, QtGui
import pyqtgraph as pg
import numpy as np
import sys
import signal
import os.path


#lasagna modules
import imageStackLoader                  # To load TIFF and MHD files
from lasagna_axis import projection2D      # The class that runs the axes
import imageProcessing                   # A potentially temporary module that houses general-purpose image processing code
import pluginHandler                     # Deals with finding plugins in the path, etc
import lasagna_mainWindow                 # Derived from designer .ui files built by pyuic
import lasagna_helperFunctions as lasHelp # Module the provides a variety of import functions (e.g. preference file handling)



#Parse command-line input arguments
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("-D", help="Load demo images", action="store_true")
parser.add_argument("-red", help="file name for red channel (if only this is specified we get a gray image)")
parser.add_argument("-green", help="file name for green channel. Only processed if a red channel was provided")
args = parser.parse_args()



fnames=[None,None]
if args.D==True:
    import tempfile
    import urllib

    fnames = [tempfile.gettempdir()+os.path.sep+'reference.tiff',
              tempfile.gettempdir()+os.path.sep+'sample.tiff']

    loadUrl = 'http://mouse.vision/lasagna/'
    for fname in fnames:
        if not os.path.exists(fname):
            url = loadUrl + fname.split(os.path.sep)[-1]
            print 'Downloading %s to %s' % (url,fname)
            urllib.urlretrieve(url,fname)
    
else:
    if args.red != None:
        fnames[0] =args.red
    if args.green != None:
        fnames[1] =args.green
    





# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
#Set up the figure window
class lasagna(QtGui.QMainWindow, lasagna_mainWindow.Ui_lasagna_mainWindow):

    def __init__(self, parent=None):
        """
        Create default values for properties then call initialiseUI to set up main window
        """
        super(lasagna, self).__init__(parent)

        #Create widgets defined in the designer file
        #self.win = QtGui.QMainWindow()
        self.setupUi(self)
        self.show()


        #Misc. window set up 
        self.setWindowTitle("Lasagna - 3D sectioning volume visualiser")
        self.recentLoadActions = [] 
        self.updateRecentlyOpenedFiles()
        
        #set up axes 
        #TODO: could more tightly integrate these objects with the main window so no need to pass many of these args?
        #TODO: stop calling these three views by thei neuroanatomical names. These can be labels, but shouldn't be harcoded as the
        #      names of the object instances
        print ""
        self.coronal  = projection2D(self.graphicsView_1,  axisRatio=float(self.axisRatioLineEdit_1.text()),  axisToPlot=0)
        self.sagittal = projection2D(self.graphicsView_2,  axisRatio=float(self.axisRatioLineEdit_2.text()),  axisToPlot=1)
        self.transverse = projection2D(self.graphicsView_3, axisRatio=float(self.axisRatioLineEdit_3.text()), axisToPlot=2)
        print ""


        #Establish links between projections for panning and zooming
        linksC = {
                    self.sagittal.view.getViewBox(): {'linkX':None, 'linkY':'y', 'linkZoom':True}  ,
                    self.transverse.view.getViewBox(): {'linkX':'x', 'linkY':None, 'linkZoom':True} 
                 }
        self.coronal.view.getViewBox().linkedAxis = linksC


        linksS = {
                    self.coronal.view.getViewBox(): {'linkX':None, 'linkY':'y', 'linkZoom':True}  ,
                    self.transverse.view.getViewBox(): {'linkX':'y', 'linkY':None, 'linkZoom':True} 
                 }
        self.sagittal.view.getViewBox().linkedAxis = linksS


        linksT = {
                    self.coronal.view.getViewBox(): {'linkX':'x', 'linkY':None, 'linkZoom':True}  ,
                    self.sagittal.view.getViewBox(): {'linkX':None, 'linkY':'x', 'linkZoom':True} 
                 }
        self.transverse.view.getViewBox().linkedAxis = linksT



        #Establish links between projections for scrolling through slices [implemented by signals in main() after the GUI is instantiated]
        self.coronal.linkedXprojection = self.transverse
        self.coronal.linkedYprojection = self.sagittal

        self.transverse.linkedXprojection = self.coronal
        self.transverse.linkedYprojection = self.sagittal

        self.sagittal.linkedXprojection = self.transverse
        self.sagittal.linkedYprojection = self.coronal




        #Initialise default values
        self.imageStack = None
        self.overlayLoaded = False
        self.baseImageFname = ''
        self.overlayImageFname = ''

        #UI elements updated during mouse moves over an axis
        self.crossHairVLine = None
        self.crossHairHLine = None
        self.showCrossHairs = lasHelp.readPreference('showCrossHairs')
        self.mouseX = None
        self.mouseY = None
        self.pixelValue = None
        self.statusBarText = None

        #Lists of functions that are used as hooks for plugins to modify the behavior of built-in methods.
        #Hooks are named using the following convention: <lasagnaMethodName_[Start|End]> 
        #So:
        # 1. It's obvious which method will call a given hook list. 
        # 2. _Start indicates the hook will run at the top of the methdd, potentiall modifying all
        #    subsecuent behavior of the method.
        # 3. _End indicates that the hook will run at the end of the method, appending its functionality
        #    to whatever the method normally does. 
        self.hooks = {
            'updateStatusBar_End'       :     [] ,
            'loadBaseImageStack_Start'  :     [] ,
            'loadBaseImageStack_End'    :     [] ,
            'removeCrossHairs_Start'    :     [] , 
            'showBaseStackLoadDialog_Start' : [] ,
            'updateMainWindowOnMouseMove_End' : []
                    }

        # Link menu signals to slots
        self.actionOpen.triggered.connect(self.showBaseStackLoadDialog)
        self.actionLoadOverlay.triggered.connect(self.showOverlayLoadDialog)
        self.actionQuit.triggered.connect(self.quitLasagna)

        # Link toolbar signals to slots
        self.actionResetAxes.triggered.connect(self.resetAxes)
        self.actionRemoveOverlay.triggered.connect(self.removeOverlay)

        #Link tabbed view items to slots
        self.axisRatioLineEdit_1.textChanged.connect(self.axisRatio1Slot)
        self.axisRatioLineEdit_2.textChanged.connect(self.axisRatio2Slot)
        self.axisRatioLineEdit_3.textChanged.connect(self.axisRatio3Slot)
        self.logYcheckBox.clicked.connect(self.plotImageStackHistogram)



        #Plugins menu and initialisation
        # 1. Get a list of a plugins in the plugins path and add their directories to the Python path
        pluginPaths = lasHelp.readPreference('pluginPaths')

        plugins, pluginPaths = pluginHandler.findPlugins(pluginPaths)
        print "Adding plugin paths to Python path"
        print pluginPaths
        [sys.path.append(p) for p in pluginPaths] #append

        # 2. Add each plugin to a dictionary where the keys are plugin name and values are instances of the plugin. 
        print ""
        self.plugins = {} #A dictionary where keys are plugin names and values are plugin classes or plugin instances
        self.pluginActions = {} #A dictionary where keys are plugin names and values are QActions associated with a plugin
        for thisPlugin in plugins:

            #Get the module name and class
            pluginClass, pluginName = pluginHandler.getPluginInstanceFromFileName(thisPlugin,None) 

            #create instance of the plugin object and add to the self.plugins dictionary
            print "Creating reference to class " + pluginName +  ".plugin"
            self.plugins[pluginName] = pluginClass.plugin

            #create an action associated with the plugin and add to the self.pluginActions dictionary
            print "Creating menu QAction for " + pluginName 
            self.pluginActions[pluginName] = QtGui.QAction(pluginName,self)
            self.pluginActions[pluginName].setObjectName(pluginName)
            self.pluginActions[pluginName].setCheckable(True) #so we have a checkbox next to the menu entry

            self.menuPlugins.addAction(self.pluginActions[pluginName]) #add action to the plugins menu
            self.pluginActions[pluginName].triggered.connect(self.startStopPlugin) #Connect this action's signal to the slot


        print ""


        self.statusBar.showMessage("Initialised")






    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Plugin-related methods
    def startStopPlugin(self):
        pluginName = str(self.sender().objectName()) #Get the name of the action that sent this signal

        if self.pluginActions[pluginName].isChecked():
           self.startPlugin(pluginName)
        else:
            self.stopPlugin(pluginName)                    


    def startPlugin(self,pluginName):
        print "Starting " + pluginName
        self.plugins[pluginName] = self.plugins[pluginName](self) #Create an instance of the plugin object 


    def stopPlugin(self,pluginName):
        print "Stopping " + pluginName
        self.plugins[pluginName].closePlugin() #tidy up the plugin
        #delete the plugin instance and replace it in the dictionary with a reference (that what it is?) to the class
        #NOTE: plugins with a window do not run the following code when the window is closed. They should, however, 
        #detach hooks (unless the plugin author forgot to do this)
        del(self.plugins[pluginName])
        pluginClass, pluginName = pluginHandler.getPluginInstanceFromFileName(pluginName+".py",None) 
        self.plugins[pluginName] = pluginClass.plugin


    def runHook(self,hookArray):
        """
        loops through list of functions and runs them
        """
        if len(hookArray) == 0 :
            return

        for thisHook in hookArray:
            try:
                if thisHook == None:
                    print "Skipping empty hook in hook list"
                    continue
                else:
                     thisHook()
            except:
                print  "Error running plugin method " + str(thisHook) 
                raise

  
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # File menu and methods associated with file loading
    def loadImageStack(self,thisFname):
        """
        Loads an image stack defined by the string thisFname and returns it as an output argument
        """
        if not os.path.isfile(thisFname):
            msg = 'Unable to find ' + thisFname
            print msg
            self.statusBar.showMessage(msg)
            return

        #TODO: The axis swap likely shouldn't be hard-coded here
        return imageStackLoader.loadStack(thisFname).swapaxes(1,2) 
 

    def loadBaseImageStack(self,fnameToLoad):
        """
        Loads the base image image stack. The base image stack is the one which will appear as gray
        if it is the only stack loaded. If an overlay is added on top of this, the base image will
        become red. This function wipes and data that have already been loaded. Any overlays that 
        are present will be removed when this function runs. 
        """

        self.baseImageFname='' #wipe this just in case loading fails

        self.runHook(self.hooks['loadBaseImageStack_Start'])
        print "Loading " + fnameToLoad
        imageStack = self.loadImageStack(fnameToLoad)

        # Set up default values in tabs
        axRatio = imageStackLoader.getVoxelSpacing(fnameToLoad)
        self.axisRatioLineEdit_1.setText( str(axRatio[0]) )
        self.axisRatioLineEdit_2.setText( str(axRatio[1]) )
        self.axisRatioLineEdit_3.setText( str(axRatio[2]) )


        imageStack = np.expand_dims(imageStack,3) #TODO: AXIS
        self.imageStack=imageStack

        for ii in (1,2): #TODO: AXIS
            self.imageStack = np.append(self.imageStack, imageStack, axis=3) #make gray image

        self.overlayEnableActions()

        #remove any existing highlighter on the histogram. We do this because different images
        #will likely have different default ranges
        if hasattr(self,'plottedIntensityRegionObj'):
            del self.plottedIntensityRegionObj

        #Log the identity of the currently loaded base file
        fname = fnameToLoad.split(os.path.sep)[-1]
        self.baseImageFname=fname

        self.runHook(self.hooks['loadBaseImageStack_End'])


    def loadOverlayImageStack(self,fnameToLoad):
        """
        Load an image stack and insert it as channel 2 into the pre-existing base stack.
        This creates a red/green overlay
        """
        self.overlayImageFname='' #wipe this just in case loading fails
        if self.imageStack == None:
            self.actionLoadOverlay.setEnabled(False)
            return

        overlayStack = self.loadImageStack(fnameToLoad) 

        existingSize = self.imageStack.shape
        overlaySize = overlayStack.shape

        if not existingSize[0:-1] == overlaySize:
            msg = '*** Overlay is not the same size as the loaded image ***'
            print msg
            self.statusBar.showMessage(msg)
            return

        #Log the identity of the currently loaded overlay file
        fname = fnameToLoad.split(os.path.sep)[-1]
        self.overlayImageFname=fname

        #TODO: AXIS
        self.imageStack[...,1] = overlayStack #fill green channel 
        self.imageStack[...,2] = 0  #Commenting out this line will produce a green/magenta image

        self.overlayEnableActions()
        self.overlayLoaded=True


    # -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  
    #Code to handle file load dialogs
    def showFileLoadDialog(self):
        """
        Bring up the file load dialog. Return the file name. Update the last used path. 
        """
        fname = QtGui.QFileDialog.getOpenFileName(self, 'Open file', lasHelp.readPreference('lastLoadDir'),  "Images (*.mhd *.mha *.tiff *.tif)" )
        fname = str(fname)
        if len(fname) == 0:
            return None

        #Update last loaded directory 
        lasHelp.preferenceWriter('lastLoadDir', lasHelp.stripTrailingFileFromPath(fname))

        #Keep a track of the last loaded files
        recentlyLoaded = lasHelp.readPreference('recentlyLoadedFiles')
        n = lasHelp.readPreference('numRecentFiles')
        recentlyLoaded.append(fname)
        recentlyLoaded = list(set(recentlyLoaded)) #get remove repeats (i.e. keep only unique values)

        while len(recentlyLoaded)>n:
            recentlyLoaded.pop(-1)

        lasHelp.preferenceWriter('recentlyLoadedFiles',recentlyLoaded)
        self.updateRecentlyOpenedFiles()

        return fname


    def showBaseStackLoadDialog(self):
        """
        Bring up the file load dialog to load the base image stack
        """
        self.runHook(self.hooks['showBaseStackLoadDialog_Start'])
        fname = self.showFileLoadDialog()
        if fname == None:
            return

        if os.path.isfile(fname): 
            self.loadBaseImageStack(str(fname)) #convert from QString and load
            #TODO: set the voxel sizes if this information was available at load time (e.g. from the MHD file)
            self.initialiseAxes()
        else:
            self.statusBar.showMessage("Unable to find " + str(fname))


    def showOverlayLoadDialog(self):
        """
        Bring up the file load dialog to load the overlay image stack
        """
        fname = self.showFileLoadDialog()
        if fname == None:
            return

        if os.path.isfile(fname): 
            self.loadOverlayImageStack(str(fname)) #convert QString and load
            self.initialiseAxes()
        else:
            self.statusBar.showMessage("Unable to find " + str(fname))


    def updateRecentlyOpenedFiles(self):
        """
        Updates the list of recently opened files
        """
        recentlyLoadedFiles = lasHelp.readPreference('recentlyLoadedFiles')

        #Remove existing actions if present
        if len(self.recentLoadActions)>0 and len(recentlyLoadedFiles)>0:
            for thisAction in self.recentLoadActions:
                self.menuOpen_recent.removeAction(thisAction)
            self.recentLoadActions = []

        for thisFile in recentlyLoadedFiles:
            self.recentLoadActions.append(self.menuOpen_recent.addAction(thisFile)) #add action to list
            self.recentLoadActions[-1].triggered.connect(self.loadRecentFileSlot) #link it to a slot
            #NOTE: tried the lambda approach but it always assigns the last file name to the list to all signals
            #      http://stackoverflow.com/questions/940555/pyqt-sending-parameter-to-slot-when-connecting-to-a-signal

    def loadRecentFileSlot(self):
        """
        load a file from recently opened list
        """
        fname = str(self.sender().text())
        self.loadBaseImageStack(fname)
        self.initialiseAxes()


    def quitLasagna(self):
        """
        Neatly shut down the GUI
        """
        #Loop through and shut plugins. 
        for thisPlugin in self.pluginActions.keys():
            if self.pluginActions[thisPlugin].isChecked():
                if not self.plugins[thisPlugin].confirmOnClose: #TODO: handle cases where plugins want confirmation to close
                    self.stopPlugin(thisPlugin)

        QtGui.qApp.quit()

    def closeEvent(self, event):
        self.quitLasagna()
    # -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -           


    def clearAxes(self):
        """
        Wipes image stack and clears plot windows
        """
        #TODO: AXIS
        self.imageStack=np.zeros([1,1,1,3]) #TODO: presumbably there is some less shit way of doing this
        self.initialiseAxes()
        self.imageStack=None
        self.overlayDisableActions()


    def resetAxes(self):
        """
        Set X and Y limit of each axes to fit the data
        """
        if self.imageStack == None:
            return

        self.coronal.resetAxes()
        self.sagittal.resetAxes()
        self.transverse.resetAxes()


    def initialiseAxes(self):
        """
        Initial display of images in axes and also update other parts of the GUI. 
        """
        if self.imageStack == None:
            return

        #show default images
        #TODO: AXIS
        self.coronal.showImage(self.imageStack)
        self.sagittal.showImage(self.imageStack)
        self.transverse.showImage(self.imageStack)

        #initialise cross hair
        if self.showCrossHairs:
            if self.crossHairVLine==None:
                self.crossHairVLine = pg.InfiniteLine(angle=90, movable=False)
                self.crossHairVLine.objectName = 'crossHairVLine'
            if self.crossHairHLine==None:
                self.crossHairHLine = pg.InfiniteLine(angle=0, movable=False)
                self.crossHairHLine.objectName = 'crossHairHLine'

        self.plotImageStackHistogram()

        self.coronal.view.setAspectLocked(True, float(self.axisRatioLineEdit_1.text()))
        self.sagittal.view.setAspectLocked(True, float(self.axisRatioLineEdit_2.text()))
        self.transverse.view.setAspectLocked(True, float(self.axisRatioLineEdit_3.text()))
        
        self.resetAxes()
        self.updateDisplayText()

    def updateDisplayText(self):
        #Add loaded file names to display box
        displayTxt=''
        if len(self.baseImageFname)>0:
            displayTxt = displayTxt + "<b>Base Image:</b> " + self.baseImageFname

        if len(self.overlayImageFname)>0:
            displayTxt = displayTxt + "<br>" + "<b>Overlay Image:</b> " + self.overlayImageFname            

        self.infoTextPanel.setText(displayTxt)



    def removeOverlay(self):
        """
        Remove overalay from an imageStack        
        """
        #TODO: AXIS
        self.imageStack[...,1] = self.imageStack[...,0]
        self.imageStack[...,2] = self.imageStack[...,0] #May not need to be done if user has edited code to make a magenta/green image
        self.initialiseAxes()
        self.overlayLoaded=False
        self.actionRemoveOverlay.setEnabled(False)

        #remove the file name from in the info text 
        self.overlayImageFname=''
        self.updateDisplayText()


    def overlayEnableActions(self):
        """
        Actions that need to be performed on the GUI when an overlay can be added
        """
        self.actionLoadOverlay.setEnabled(True)
        self.actionRemoveOverlay.setEnabled(True)


    def overlayDisableActions(self):
        """
        Actions that need to be performed on the GUI when an overlay can not be added
        """
        self.actionLoadOverlay.setEnabled(False)
        self.actionRemoveOverlay.setEnabled(False)
        self.overlayLoaded=False #If an overlay can not be added it also can not be present



    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Slots for axis tab
    # TODO: incorporate these three slots into one
    def axisRatio1Slot(self):
        """
        Set axis ratio on plot 1
        """
        self.coronal.view.setAspectLocked( True, float(self.axisRatioLineEdit_1.text()) )


    def axisRatio2Slot(self):
        """
        Set axis ratio on plot 2
        """
        self.sagittal.view.setAspectLocked( True, float(self.axisRatioLineEdit_2.text()) )


    def axisRatio3Slot(self):
        """
        Set axis ratio on plot 3
        """
        self.transverse.view.setAspectLocked( True, float(self.axisRatioLineEdit_3.text()) )


    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Methods that are run during navigation
    def removeCrossHairs(self):
        """
        Remove the cross hairs from all plots
        """
        # NOTE: I'm a little unhappy about this as I don't understand what's going on. 
        # I've noticed that removing the cross hairs from any one plot is sufficient to remove
        # them from the other two. However, if all three axes are not explicitly removed I've
        # seen peculiar behavior with plugins that query the PlotWidgets. RAAC 21/07/2015

        self.runHook(self.hooks['removeCrossHairs_Start']) #This will be run each time a plot is updated

        if not self.showCrossHairs:
            return

        self.coronal.view.removeItem(self.crossHairVLine) 
        self.coronal.view.removeItem(self.crossHairHLine)

        self.sagittal.view.removeItem(self.crossHairVLine) 
        self.sagittal.view.removeItem(self.crossHairHLine)

        self.transverse.view.removeItem(self.crossHairVLine) 
        self.transverse.view.removeItem(self.crossHairHLine)


    def constrainMouseLocationToImage(self,thisImage):
        """
        Ensures that the values of self.mouseX and self.mouseY, which are the X and Y positions
        of the mouse pointer on the current image, do not exceed the dimensions of the image.
        This is used to avoid asking for image slices that do not exist.
        NOTE: constraints on plotting are also imposed in lasagna_axis.showImage
        """
        #I think the following would be better placed in getMousePositionInCurrentView, but this could work also. 
        if self.mouseX<0:
            self.mouseX=0

        if self.mouseY<0:
            self.mouseY=0

        if self.mouseX>=thisImage.shape[0]:
            self.mouseX=thisImage.shape[0]-1

        if self.mouseY>=thisImage.shape[1]:
            self.mouseY=thisImage.shape[1]-1


    def updateCrossHairs(self):
        """
        Update the drawn cross hairs on the current image 
        """
        if not self.showCrossHairs:
            return
        self.crossHairVLine.setPos(self.mouseX+0.5) #Add 0.5 to add line to middle of pixel
        self.crossHairHLine.setPos(self.mouseY+0.5)


    def updateStatusBar(self,thisImage):
        """
        Update the text on the status bar based on the current mouse position 
        """
        X = self.mouseX
        Y = self.mouseY

        #get pixel value of red layer
        self.pixelValue = thisImage[X,Y] 
        if isinstance(self.pixelValue,np.ndarray): #so this works with both RGB and monochrome images
            self.pixelValue = int(self.pixelValue[0])



        self.statusBarText = "X=%d, Y=%d, val=%d" % (X,Y,self.pixelValue)

        self.runHook(self.hooks['updateStatusBar_End']) #Hook goes here to modify or append message

        self.statusBar.showMessage(self.statusBarText)


    def updateMainWindowOnMouseMove(self,thisImage):
        """
        Update UI elements on the screen (but not the plotted images) as the user moves the mouse across an axis
        """
        self.constrainMouseLocationToImage(thisImage)
        self.updateCrossHairs()
        self.updateStatusBar(thisImage)
        self.runHook(self.hooks['updateMainWindowOnMouseMove_End']) #Runs each time the views are updated



    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Image Tab methods
    # These methods are involved with the tabs to the left of the three view axes

    def plotImageStackHistogram(self):
        """
        Plot the image stack histogram in a PlotWidget to the left of the three image views.
        This function is called when the plot is first set up and also when the log Y
        checkbox is checked or unchecked
        """
        #TODO: AXIS - eventually have different histograms for each color channel
        x,y = self.coronal.img.getHistogram()

        #Determine max value on the un-logged y values. Do not run this again if the 
        #graph is merely updated. This will only run if a new imageStack was loaded
        if not hasattr(self,'plottedIntensityRegionObj'):
            calcuMaxVal = imageProcessing.coreFunctions.defaultHistRange(y,x) #return a reasonble value for the maximum

        if self.logYcheckBox.isChecked():
            y=np.log10(y+0.1)

        self.intensityHistogram.clear()
        ## Using stepMode=True causes the plot to draw two lines for each sample but it needs X to be longer than Y by 1
        self.intensityHistogram.plot(x, y, stepMode=False, fillLevel=0, brush=(255,0,255,80))

        self.intensityHistogram.showGrid(x=True,y=True,alpha=0.33)
        self.intensityHistogram.setLimits(yMin=0, xMin=0)

        #The object that represents the plotted intensity range is only set up the first time the 
        #plot is made or following a new base image being loaded (any existing plottedIntensityRegionObj
        #is deleted at base image load time.)
        if not hasattr(self,'plottedIntensityRegionObj'):
            self.plottedIntensityRegionObj = pg.LinearRegionItem()
            self.plottedIntensityRegionObj.setZValue(10)
            self.setIntensityRange( (0,calcuMaxVal) )
            self.plottedIntensityRegionObj.sigRegionChanged.connect(self.updateAxisLevels) #link signal slot

        # Add to the ViewBox but exclude it from auto-range calculations.
        self.intensityHistogram.addItem(self.plottedIntensityRegionObj, ignoreBounds=True)


    def setIntensityRange(self,intRange=(0,2**12)):
        """
        Set the intensity range of the images and update the axis labels. 
        This is really just a convenience function with an easy to remember name.
        intRange is a tuple that is (minX,maxX)
        """
        self.plottedIntensityRegionObj.setRegion(intRange)
        self.updateAxisLevels()


    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Slots relating to plotting
    def updateAxisLevels(self):
        #TODO: AXIS
        minX, maxX = self.plottedIntensityRegionObj.getRegion()
        
        self.coronal.minMax=(minX,maxX)
        self.coronal.img.setLevels([minX,maxX])
        
        self.sagittnal.minMax=(minX,maxX)
        self.sagittal.img.setLevels([minX,maxX])
        
        self.transverse.minMax=(minX,maxX)
        self.transverse.img.setLevels([minX,maxX])
        


    def mouseMovedCoronal(self,evt):
        if self.imageStack == None:
            return

        pos = evt[0] #Using signal proxy turns original arguments into a tuple
        self.removeCrossHairs()

        if self.coronal.view.sceneBoundingRect().contains(pos):
            #TODO: figure out how to integrate this into object, because when we have that, we could
            #      do everything but the axis linking in the object. 
            if self.showCrossHairs:
                self.coronal.view.addItem(self.crossHairVLine, ignoreBounds=True)
                self.coronal.view.addItem(self.crossHairHLine, ignoreBounds=True)

            (self.mouseX,self.mouseY)=self.coronal.getMousePositionInCurrentView(pos)
            self.updateMainWindowOnMouseMove(self.coronal.img.image)
            self.coronal.updateDisplayedSlices(self.imageStack,(self.mouseX,self.mouseY))


    def mouseMovedSaggital(self,evt):
        if self.imageStack == None:
            return

        pos = evt[0]
        self.removeCrossHairs()

        if self.sagittal.view.sceneBoundingRect().contains(pos):
            if self.showCrossHairs:
                self.sagittal.view.addItem(self.crossHairVLine, ignoreBounds=True)
                self.sagittal.view.addItem(self.crossHairHLine, ignoreBounds=True)

            (self.mouseX,self.mouseY)=self.sagittal.getMousePositionInCurrentView(pos)
            self.updateMainWindowOnMouseMove(self.sagittal.img.image)
            self.sagittal.updateDisplayedSlices(self.imageStack,(self.mouseX,self.mouseY))

        
    def mouseMovedTransverse(self,evt):
        if self.imageStack == None:
            return

        pos = evt[0]  
        self.removeCrossHairs()

        if self.transverse.view.sceneBoundingRect().contains(pos):
            if self.showCrossHairs:
                self.transverse.view.addItem(self.crossHairVLine, ignoreBounds=True) 
                self.transverse.view.addItem(self.crossHairHLine, ignoreBounds=True)

            (self.mouseX,self.mouseY)=self.transverse.getMousePositionInCurrentView(pos)
            self.updateMainWindowOnMouseMove(self.transverse.img.image)
            self.transverse.updateDisplayedSlices(self.imageStack,(self.mouseX,self.mouseY))






# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

def main(fnames=[None,None]):
    app = QtGui.QApplication([])

    tasty = lasagna()

    #Load stacks from command line input if any was provided
    if not fnames[0]==None:
        print "Loading " + fnames[0]
        tasty.loadBaseImageStack(fnames[0])
    
        if not fnames[1]==None:
            print "Loading " + fnames[1]
            tasty.loadOverlayImageStack(fnames[1])

        tasty.initialiseAxes()


    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # Link slots to signals
    #connect views to the mouseMoved slot. After connection this runs in the background. 
    #TODO: figure out why returning an argument is crucial even though we never use it
    proxy1=pg.SignalProxy(tasty.coronal.view.scene().sigMouseMoved, rateLimit=30, slot=tasty.mouseMovedCoronal)
    proxy2=pg.SignalProxy(tasty.sagittal.view.scene().sigMouseMoved, rateLimit=30, slot=tasty.mouseMovedSaggital)
    proxy3=pg.SignalProxy(tasty.transverse.view.scene().sigMouseMoved, rateLimit=30, slot=tasty.mouseMovedTransverse)

    sys.exit(app.exec_())

## Start Qt event loop unless running in interactive mode.
if __name__ == '__main__':
    main(fnames=fnames)


    """
    original_sigint = signal.getsignal(signal.SIGINT)
    if (sys.flags.interactive != 1) or not hasattr(QtCore, 'PYQT_VERSION'):
        QtGui.QApplication.instance().exec_()
    """