"""
Loads data from imagej/fiji ROIs or ROIs sets (zip files)

Requires ijroi from: https://github.com/tdsmith/ijroi/blob/master/ijroi/ijroi.py
`pip install ijroi` to get it.


"""
import os


try:
    import ijroi
except ImportError:
    print('fiji_roi_reader_plugin requires the ijroi module from:\n'
          '  https://github.com/tdsmith/ijroi/blob/master/ijroi/ijroi.py.'
          '  Use `pip install ijroi` to get it.')
    raise

import numpy as np

from lasagna.plugins.io.io_plugin_base import IoBasePlugin


class loaderClass(IoBasePlugin):
    def __init__(self, lasagna_serving):
        self.objectName = 'fiji_roi_reader'
        self.kind = 'sparsepoints'
        self.icon_name = 'points'
        self.actionObjectName = 'fijiPointRead'  # FIXME: rename or find way to compute from objectName
        super(loaderClass, self).__init__(lasagna_serving)

    # Slots follow
    def showLoadDialog(self, fname=None):
        """
        This slot brings up the load dialog and retrieves the file name.
        If a filename is provided then this is loaded and no dialog is brought up.
        If the file name is valid, it loads the image stack using the load method.

        """

        if not fname:
            fname = self.lasagna.showFileLoadDialog(fileFilter="ImageJ ROIs (*.roi *.zip)")

        if not fname:
            return

        if os.path.isfile(fname):
            if fname.endswith('.zip'):
                rois = ijroi.read_roi_zip(fname)
            else:
                rois = []

            # a list of strings with each string being one line from the file
            as_list = contents.split('\n')
            data = []
            for i in range(len(as_list)):
                if len(as_list[i]) == 0:
                    continue
                data.append([float(x) for x in as_list[i].split(',')])

            # A point series should be a list of lists where each list has a length of 3,
            # corresponding to the position of each point in 3D space. However, point
            # series could also have a length of 4. If this is the case, the fourth
            # value is the index of the series. This allows a single file to hold multiple
            # different point series. We handle these two cases differently. First we deal
            # with the the standard case:
            if len(data[1]) == 3:
                # Create an ingredient with the same name as the file name
                objName = fname.split(os.path.sep)[-1]
                self.lasagna.addIngredient(object_name=objName,
                                           kind=self.kind,
                                           data=np.asarray(data),
                                           fname=fname
                                           )

                # Add this ingredient to all three plots
                self.lasagna.returnIngredientByName(obj_name).addToPlots()

                # Update the plots
                self.lasagna.initialiseAxes()
            elif len(data[1]) == 4:
                # What are the unique data series values?
                d_series = [x[3] for x in data]
                d_series = list(set(d_series))

                # Loop through these unique series and add as separate sparse point objects

                for idx in d_series:
                    tmp = []
                    for thisRow in data:
                        if thisRow[3] == idx:
                            tmp.append(thisRow[:3])

                    print("Adding point series %d with %d points" % (idx, len(tmp)))

                    # Create an ingredient with the same name as the file name
                    obj_name = "%s #%d" % (fname.split(os.path.sep)[-1], idx)

                    self.lasagna.addIngredient(object_name=objName,
                                               kind=self.kind,
                                               data=np.asarray(tmp),
                                               fname=fname
                                               )

                    # Add this ingredient to all three plots
                    self.lasagna.returnIngredientByName(obj_name).addToPlots()

                    # Update the plots
                    self.lasagna.initialiseAxes()
            else:
                print(("Point series has %d columns. Only 3 or 4 columns are supported" % len(data[1])))
        else:
            self.lasagna.statusBar.showMessage("Unable to find " + str(fname))
