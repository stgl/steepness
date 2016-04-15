#Functions for DEM calculations typical of geomorphology
#Developed by Sam Johnstone, January 2015, samuelj@stanford.edu , johnsamstone@gmail.com
#Not all functions are benchmarked
#If you somehow have this, and have never spoken to me, please reach out
#- I'd be curious to hear what you are doing (maybe I can even help with something!)

from osgeo import gdal # Used to load gis in files
import osr # Used with gis files
from osgeo import ogr
import os # Used to join file paths, iteract with os in other ways..
import glob  # Used for finding files that I want to mosaic (by allowing wildcard searches of the filesystem)
import heapq # Used for constructing priority queue, which is used for filling dems
import numpy as np # Used for tons o stuff, keeping most data stored as numpy arrays
import subprocess # Used to run gdal_merge.py from the command line
import Error
from aifc import data


class GDALMixin(object):
    
    def _get_projection_from_EPSG_projection_code(self, EPSGprojectionCode):
        # Get raster projection
        srs = osr.SpatialReference()
        return srs.ImportFromEPSG(EPSGprojectionCode).ExportToWkt()

    def _get_gdal_type_for_numpy_type(self, numpy_type):
    
        from numpy import float64, uint8, uint16, int16, uint32, int32, float32, complex64
        from gdal import GDT_Byte, GDT_UInt16, GDT_Int16, GDT_UInt32, GDT_Int32, GDT_Float32, GDT_Float64, GDT_CFloat64, GDT_Unknown
        
        type_map = { uint8: GDT_Byte,
                uint16: GDT_UInt16,
                int16: GDT_Int16,
                uint32: GDT_UInt32,
                int32: GDT_Int32,
                float32: GDT_Float32,
                float64: GDT_Float64,
                complex64: GDT_CFloat64 }
        
        gdal_type = type_map.get(numpy_type)
        
        if gdal_type is None:
            return GDT_Unknown
        else:
            return gdal_type
    
    def _get_numpy_type_for_gdal_type(self, gdal_type):
        
        from numpy import float64, uint8, uint16, int16, uint32, int32, float32, complex64
        from gdal import GDT_Byte, GDT_UInt16, GDT_Int16, GDT_UInt32, GDT_Int32, GDT_Float32, GDT_Float64, GDT_CFloat64
                    
        type_map = { GDT_Byte: uint8,
                GDT_UInt16: uint16,
                GDT_Int16: int16,
                GDT_UInt32: uint32,
                GDT_Int32: int32,
                GDT_Float32: float32,
                GDT_Float64: float64,
                GDT_CFloat64: complex64}
        
        numpy_type = type_map.get(gdal_type)
        
        if numpy_type is None:
            return float64
        else:
            return numpy_type
    
    def _readGDALFile(self, filename, dtype):
        gdal_file = gdal.Open(filename)
        geoTransform, nx, ny, data = self._read_GDAL_dataset(gdal_file, dtype)
        gdal_file = None
        return geoTransform, nx, ny, data
        
    def _read_GDAL_dataset(self, gdal_dataset, dtype):
        data = gdal_dataset.ReadAsArray().astype(dtype)
        geoTransform = gdal_dataset.GetGeoTransform()
        nx = gdal_dataset.RasterXSize
        ny = gdal_dataset.RasterYSize
        return geoTransform, nx, ny, data
    
    def _getGeoRefInfo(self, gdalDataset):
        #Get info needed to initialize new dataset
        nx = gdalDataset.RasterXSize
        ny = gdalDataset.RasterYSize
    
        #Write geographic information
        geoTransform = gdalDataset.GetGeoTransform()  # Steal the coordinate system from the old dataset
        projection = gdalDataset.GetProjection()  # Steal the Projections from the old dataset
    
        return nx, ny, projection, geoTransform
 
 
    def getDEMcoords(self, GdalData, dx):
    
        #Get grid size
        nx, ny = GdalData.RasterXSize, GdalData.RasterYSize
    
        #Get information about the spatial reference
        (upper_left_x, x_size, x_rotation, upper_left_y, y_rotation, y_size) = GdalData.GetGeoTransform()
        xllcenter = upper_left_x + dx/2.0  # x coordinate center of lower left pxl
        yllcenter = upper_left_y - (ny-0.5)*dx # y coordinate center of lower left pxl
    
        #Create arrays of the x and y coordinates of each pixel (the axes)
        xcoordinates = [x*dx + xllcenter for x in range(nx)]
        ycoordinates = [y*dx + yllcenter for y in range(ny)][::-1] #Flip the ys so that the first row corresponds to the first entry of this array
    
        return xcoordinates, ycoordinates

    def _create_gdal_representation_from_array(self, georef_info, GDALDRIVERNAME, array_data, dtype, outfile_path='name'):
        #A function to write the data in the numpy array arrayData into a georeferenced dataset of type
        #  specified by GDALDRIVERNAME, a string, options here: http://www.gdal.org/formats_list.html
        #  This is accomplished by copying the georeferencing information from an existing GDAL dataset,
        #  provided by createDataSetFromArray
    
        #Initialize new data
        drvr = gdal.GetDriverByName(GDALDRIVERNAME)  #  Get the desired driver
        outRaster = drvr.Create(outfile_path, georef_info.nx, georef_info.ny, 1 , self._get_gdal_type_for_numpy_type(dtype))  # Open the file
    
        #Write geographic information
        outRaster.SetGeoTransform(georef_info.geoTransform)  # Steal the coordinate system from the old dataset
        outRaster.SetProjection(georef_info.projection)   # Steal the Projections from the old dataset
    
        #Write the array
        outRaster.GetRasterBand(1).WriteArray(array_data)   # Writes my array to the raster
        return outRaster
   
    def _clipRasterToRaster(self, input_gdal_dataset, clipping_gdal_dataset, dtype):

        # Source
        src_proj = input_gdal_dataset.GetProjection()
        src_geotrans = input_gdal_dataset.GetGeoTransform()
    
        # We want a section of source that matches this:
        match_proj = clipping_gdal_dataset.GetProjection()
        match_geotrans = clipping_gdal_dataset.GetGeoTransform()
        wide = clipping_gdal_dataset.RasterXSize
        high = clipping_gdal_dataset.RasterYSize
    
        # Output / destination
        dst = gdal.GetDriverByName('MEM').Create('name', wide, high, 1, dtype)
        dst.SetGeoTransform( match_geotrans )
        dst.SetProjection( match_proj)
    
        # Do the work
        gdal.ReprojectImage(input_gdal_dataset, dst, src_proj, match_proj, gdal.GRA_Bilinear)
        # gdal.ReprojectImage(src, dst, None, None, GRA_Bilinear)
        # gdal.ReprojectImage(dst, src, None, None, GRA_Bilinear)
    
        #
        return dst
 
    def _clipRasterToShape(self, raster, shape):
        
        # TODO: This needs implementation to write out the raster and shape files, execute the warp, read in the resulting file, and delete the filenames.  What a hack.
        
        # drvr = gdal.GetDriverByName(GdalDriver)
        # drvr.Create(outputFilename,1,1,1)
    #    warp= 'gdalwarp -cutline \'%s\' -crop_to_cutline -dstalpha \'%s\' \'%s\'' % (shpFilename, srcFilename, outputFilename)
        
        warp= 'gdalwarp -cutline \'%s\' -crop_to_cutline \'%s\' \'%s\'' % (shpFilename, srcFilename, outputFilename)
    
        os.system(warp)
    
    def _convertToUTM(self, dataset, dx, utmZone):

        #Get Spatial reference info
        oldRef = osr.SpatialReference()  # Initiate a spatial reference
    
        oldRef.ImportFromWkt(dataset.GetProjectionRef())  # Clone the spatial reference from the dataset
    
        newRef = osr.SpatialReference()
        newRef.SetUTM(abs(utmZone), utmZone > 0)
    
        #Set up the transform
        transform = osr.CoordinateTransformation(oldRef, newRef) # Create the coordinate transform object
        tVect = dataset.GetGeoTransform()  # Get the coordinate transform vector
        nx, ny = dataset.RasterXSize, dataset.RasterYSize  # Size of the original raster
        (ulx, uly, ulz ) = transform.TransformPoint(tVect[0], tVect[3])
        (lrx, lry, lrz ) = transform.TransformPoint(tVect[0] + tVect[1]*nx, tVect[3] + tVect[5]*ny)
        memDrv = gdal.GetDriverByName('MEM')  # Create a gdal driver in memory
        dataOut = memDrv.Create('name', int((lrx - ulx)/dx), int((uly - lry)/dx), 1, gdal.GDT_Float32)
        newtVect = (ulx, dx, tVect[2], uly, tVect[4], -dx)
    
    
        dataOut.SetGeoTransform(newtVect)  # Set the new geotransform
        dataOut.SetProjection(newRef.ExportToWkt())
        # Perform the projection/resampling
        res = gdal.ReprojectImage(dataset, dataOut, oldRef.ExportToWkt(), newRef.ExportToWkt(), gdal.GRA_Cubic)
    
        return dataOut
    
    def _getRasterGeoTransformFromAsciiRaster(self, fileName):
        #Read in the components of the geotransform from the raster, BEWARE! This
        #is specific to how some matlab/ C scripts I have write these rasters. I believe
        #this is that standard arc ascii raster export format, but could be wrong
        georef_data = dict()
        
        with open(fileName, "r") as ascii_file:
            for _ in xrange(5):
                line = ascii_file.readline()
                (key, value) = (line.split()[1], int(line.split()[-1]))
                georef_data[key.lower()] = value

        required_values = ('ncols', 'nrows', 'cellsize','nodata_value')
        
        if len(set(required_values).subtract(set(georef_data.keys()))) != 0:
            raise Error.InputError('A/I ASCII grid error','The following properties are missing: ' + set(required_values).subtract(set(georef_data.keys())))
        
        if georef_data.get('xllcorner') is None and georef_data.get('xllcenter') is None:
            raise Error.InputError('A/I ASCII grid error','Neither XLLCorner nor XLLCenter is present.')
        
        if georef_data.get('yllcorner') is None and georef_data.get('yllcenter') is None:
            raise Error.InputError('A/I ASCII grid error','Neither YLLCorner nor YLLCenter is present.')
        
        dx = georef_data.get('cellsize')
        nx = georef_data.get('ncols')
        ny = georef_data.get('nrows')
        
        if georef_data.get('xllcenter') is not None:
            xUL = georef_data.get('xllcenter') - (dx/2.0)
        else:
            xUL = georef_data.get('xllcorner');
        
        if georef_data.get('yllcenter') is not None:
            yUL = (georef_data.get('yllcenter') - (dx/2.0)) + dx*ny
        else:
            yUL = georef_data.get('yllcorner') + dx*ny
    
        return (xUL, dx, 0, yUL, 0, -dx), nx, ny
    
    def _writeArcAsciiRaster(self, georef_info, outfile_path, np_array_data, nodata_value, format_string):
        #A function to write the data stored in the numpy array npArrayData to a ArcInfo Text grid. Gdal doesn't
        #allow creation of these types of data for whatever reason
    
        header = "ncols     %s\n" % georef_info.ncols
        header += "nrows    %s\n" % georef_info.nrows
        header += "xllcenter %s\n" % georef_info.xllcenter
        header += "yllcenter %s\n" % georef_info.yllcenter
        header += "cellsize %s\n" % georef_info.dx
        header += "NODATA_value %s" % nodata_value
    
        np.savetxt(outfile_path, np_array_data, header=header, fmt=format_string, comments='')
    
    def _asciiRasterToMemory(self, fileName):

        # the geotransfrom structured as (xUL, dx, skewX, yUL, scewY, -dy)
        gt, nx, ny = self._getRasterGeoTransformFromAsciiRaster(fileName)
    
        #Open gdal dataset
        ds = gdal.Open(fileName)
    
        #Prep output
        memDrv = gdal.GetDriverByName('MEM')  # Create a gdal driver in memory
        dataOut = memDrv.CreateCopy('name', ds, 0) #Copy data to gdal driver
    
        data = dataOut.ReadAsArray(dtype = self.dtype)
        dataOut = None
        
        return gt, nx, ny, data

class GeographicGridMixin(object):
    
    def _getUTMZone(self, dataset):
        #Function to get the approximate UTM zone %NOTE: I need to check how east and west are handled...
    
        #Utm zone boundary (zones are numbered in order, 1:60) #NEED TO DOUBLE CHECK THIS
        westBound = np.array([-180 + x*6 for x in range(60)]) #west boundary of 6 degree UTM zone bounds
        eastBound = np.array([-174 + x*6 for x in range(60)]) #east boundary of 6 degree UTM zone bounds
    
        #Midpoint of dataset
        tVect = dataset.GetGeoTransform()  # Get the coordinate transform vector, (ulx, dx, xRot, uly, yRot, -dx)
        nx, ny = dataset.RasterXSize, dataset.RasterYSize #Get the number of colums and rows
        midLat = tVect[3]-tVect[1]*ny/2.0 #half way down the dataset
        midLong = tVect[0]+tVect[1]*nx/2.0 #half way across the dataset
    
        #Convert UTM zone to negative to distinguish it as south (if appropriate)
        southMultiplier = 1
        if midLat < 0:
            southMultiplier = -1
    
        #The utm zone, the index of the boundaries that surround the point incremented to account for pythons 0 indexing
        zone = np.nonzero(np.logical_and(midLong > westBound, midLong < eastBound))[0] + 1
    
        return zone*southMultiplier

    def _getLatsLongsFromGeoTransform(self, geoTransform, nx, ny):
        dLong = geoTransform[1]
        dLat = geoTransform[5]
    
        #Determine the location of the center of the first pixel of the data
        xllcenter = geoTransform[0]+dLong/2.0
        yllcenter = geoTransform[3]+dLat/2.0
    
        #Assign the latitudinal (i.e. y direction) coordinates
        lats = np.zeros(ny)
        for i in range(len(lats)):
            lats[i] = yllcenter + i*dLat
    
        #Assign the longitudinal (i.e. x direction) coordinates
        longs = np.zeros(nx)
        for i in range(len(longs)):
            longs[i] = xllcenter + i*dLong
    
        return lats,longs
    
    def _approximateDxFromGeographicData(self, geoTransform):
        #Function to return the approximate grid spacing in Meters. Will return the closest integer value
        dTheta = geoTransform[1] #Angular grid spacing
        metersPerDegree = 110000 #110 km per degree (approximation)
        return int(dTheta*metersPerDegree) #convert degrees to meters
    
class CalculationMixin(object):
    
    def _calcFiniteSlopes(self, grid, dx):
        # sx,sy = calcFiniteDiffs(elevGrid,dx)
        # calculates finite differences in X and Y direction using the
        # 2nd order/centered difference method.
        # Applies a boundary condition such that the size and location
        # of the grids in is the same as that out.
    
        # Assign boundary conditions
        
        Zbc = self.assignBCs(grid)
    
        #Compute finite differences
        Sx = (Zbc[1:-1, 2:] - Zbc[1:-1, :-2])/(2*dx)
        Sy = (Zbc[2:,1:-1] - Zbc[:-2, 1:-1])/(2*dx)
    
        return Sx, Sy
    
    def assignBCs(self, grid, nx, ny):
        # Pads the boundaries of a grid
        # Boundary condition pads the boundaries with equivalent values
        # to the data margins, e.g. x[-1,1] = x[1,1]
        # This creates a grid 2 rows and 2 columns larger than the input
    
        Zbc = np.zeros((ny + 2, nx + 2))  # Create boundary condition array
        Zbc[1:-1,1:-1] = grid  # Insert old grid in center
    
        #Assign boundary conditions - sides
        Zbc[0, 1:-1] = grid[0, :]
        Zbc[-1, 1:-1] = grid[-1, :]
        Zbc[1:-1, 0] = grid[:, 0]
        Zbc[1:-1, -1] = grid[:,-1]
    
        #Assign boundary conditions - corners
        Zbc[0, 0] = grid[0, 0]
        Zbc[0, -1] = grid[0, -1]
        Zbc[-1, 0] = grid[-1, 0]
        Zbc[-1, -1] = grid[-1, 0]
    
        return Zbc

    def calcFiniteCurv(self, grid, dx):
        #C = calcFiniteCurv(elevGrid, dx)
        #calculates finite differnces in X and Y direction using the centered difference method.
        #Applies a boundary condition such that the size and location of the grids in is the same as that out.
    
        #Assign boundary conditions
        Zbc = self.assignBCs(grid)
    
        #Compute finite differences
        Cx = (Zbc[1:-1, 2:] - 2*Zbc[1:-1, 1:-1] + Zbc[1:-1, :-2])/dx**2
        Cy = (Zbc[2:, 1:-1] - 2*Zbc[1:-1, 1:-1] + Zbc[:-2, 1:-1])/dx**2
    
        return Cx+Cy
    
    def calcContourCurvature(self, grid,dx):
        # kt = (fxx*fy^2 - 2*fxyfxfy + fyy*fx^2)/((fx^2 + fy^2)*sqrt((fx^2 + fy^2)+1)
    
        #Preallocate
        Kt = np.zeros_like(grid)*np.nan
    
        #First derivatives, 2nd order centered difference
        fx = (grid[1:-1,2:] - grid[1:-1,:-2])/(dx*2)
        fy = (grid[2:,1:-1] - grid[:-2,1:-1])/(dx*2)
    
        #Second derivatives, 2nd order centered differece
        fxx = (grid[1:-1,2:] - 2*grid[1:-1,1:-1] + grid[1:-1,:-2])/(dx**2)
        fyy = (grid[2:,1:-1] - 2*grid[1:-1,1:-1] + grid[:-2,1:-1])/(dx**2);
    
        #Partial derivative
        fxy = (grid[2:,2:] - grid[2:,1:-1] - grid[1:-1,2:] + 2*grid[1:-1,1:-1] - grid[:-2,1:-1] - grid[1:-1,:-2] + grid[:-2,:-2])
        fxy = fxy/(4*dx**2)
    
        #Contour curvature
        Kt[1:-1, 1:-1] = (fxx*fy**2 - 2*fxy*fx*fy + fyy*fx**2)/((fx**2 + fy**2)*np.sqrt((fx**2 + fy**2)+1))
    
        return Kt

    def calcAverageSlopeOfGridSubset(self, gridSubset,dx):
        ## Sx,Sy = calcAverageSlopeOfGridSubset(numpy matrix, dx)
        #Compute the average slope over a subset of a grid (or a whole grid if you're into that),
        #by fitting a plane to the elevation data stored in grid subset
        nx,ny = len(gridSubset[1,:]), len(gridSubset[:,1])
        xs = (0.5+np.arange(nx))*dx - (nx*dx)/2.0
        ys = (0.5+np.arange(ny))*dx - (ny*dx)/2.0
        X,Y = np.meshgrid(xs,ys)
        #Fit a plane of the form z = ax + by + c, where beta = [a b c]
        M=np.vstack((X.flatten(),Y.flatten(),np.ones((1,nx*ny)))).T
        beta = np.linalg.lstsq(M,gridSubset.flatten())[0]
    
        return beta[0], beta[1] #Return the slope in the x and y directions respecticely

class BaseSpatialShape(object):
    # Wrapper for GDAL shapes.
    def __init__(self, *args, **kwargs):
        if kwargs.get('shapefile_name') is None:
            raise Error.InputError('Input Error', 'Inputs not satisfied')
        self.shapedata = ogr.Open(kwargs.get('shapefile_name'))

    def createMaskFromShape(self, geoRefInfo, projection, dtype, noDataValue = 0):
    
        #Open Shapefile
        source_ds = self.shapedata
        source_layer = source_ds.GetLayer()
    
        maskSrc = gdal.GetDriverByName('MEM').Create('name',geoRefInfo.nx,geoRefInfo.ny, 1, dtype)
        maskSrc.SetGeoTransform(geoRefInfo.geoTransform)
        maskBand = maskSrc.GetRasterBand(1)
        maskBand.SetNoDataValue(noDataValue)
    
        # 5. Rasterize why is the burn value 0... isn't that the same as the background?
        gdal.RasterizeLayer(maskSrc, [1], source_layer, burn_values=[1])
        grid = maskSrc.ReadAsArray().astype(dtype)
        maskSrc = None
        return BaseSpatialGrid(nx = geoRefInfo.nx, ny = geoRefInfo.ny, projection = projection, geo_transform = geoRefInfo.geoTransform, grid= grid)

    
class BaseSpatialGrid(object, GDALMixin):
    
    from numpy import float64
    
    required_inputs_and_actions = ((('nx', 'ny', 'projection', 'geo_transform',),'__create'),
                                   (('ai_ascii_filename','EPSGprojectionCode'),'__read_ai'),
                                   (('gdal_filename',), '__read_gdal'), )
    dtype = float64
    
    def __init__(self, *args, **kwargs):
        
        from numpy import zeros
        super(BaseSpatialGrid,self).__init(*args, **kwargs)

        evaluative_action = self.__get_evaluative_action(*args, **kwargs)
        
        if evaluative_action == None:
            raise Error.InputError('Input Error', 'Inputs not satisfied')
        
        eval('self.' + evaluative_action + '(*args, **kwargs)')
        
    def __get_evaluative_action(self, *args, **kwargs):
                
        for required_input_set, evaluative_action in self.required_inputs_and_actions:
            these_kw = set(kwargs.keys())
            required_kw = set(required_input_set)
            if len(these_kw.subtract(required_kw)) == 0:
                return evaluative_action 
        
        return None
    
    def __populate_georef_info_using_geoTransform(self, nx, ny):
        self._georef_info.dx = self._georef_info.geoTransform[1]
        self._georef_info.xllcenter = self._georef_info.geoTransform[0]+self._dx/2.0
        self._georef_info.yllcenter = self._georef_info.geoTransform[3]-(self._dx*(self._ny-0.5))
        self._georef_info.nx = nx
        self._georef_info.ny = ny
        
    def __create(self, *args, **kwargs):
            
        self._georef_info.geoTransform = kwargs.get('geo_transform')
        self._georef_info.projection = kwargs.get('projection')
        self.__populate_georef_info_using_geoTransform(kwargs['nx'], kwargs['ny'])
        if kwargs.get('grid') is None:
            self._griddata = np.zeros(shape = (self._geref_info.ny,self._georef_info.nx), dtype = self.dtype)
        else:
            self._griddata = kwargs.get('grid')

    def __read_ai(self, *args, **kwargs):
        
        self._georef_info.projection = self._get_projection_from_EPSG_projection_code(kwargs['EPSGprojectionCode'])
        self._georef_info.geoTransform, self._georef_info.nx, self._georef_info.ny, self._griddata = self._asciiRasterToMemory(kwargs['ai_ascii_filename'])
        self.__populate_georef_info_using_geoTransform(self._georef_info.nx, self._georef_info.ny)
    
    def __read_gdal(self, *args, **kwargs):
        
        self._georef_info.geoTransform, self._georef_info.nx, self._georef_info.ny, self._griddata = self._readGDALFile(kwargs['gdal_filename'], self.dtype)
        self.__populate_georef_info_using_geoTransform(self._georef_info.nx, self._georef_info.ny)
    
    def _getNeighborIndices(self, row, col):
        #Search kernel for D8 flow routing, the relative indices of each of the 8 points surrounding a pixel
        # |i-1,j-1  i-1,j  i-1,j+1|
        # |i,j-1     i,j     i,j+1|
        # |i+1,j-1  i+1,j  i+1,j+1|
        rowKernel = np.array([1, 1, 1, 0, 0, -1, -1, -1])
        colKernel = np.array([-1, 0, 1, -1, 1, -1, 0, 1])
    
        rt2 = np.sqrt(2)
        dxMults = np.array([rt2, 1.0, rt2, 1.0, 1.0, rt2, 1.0, rt2])  # Unit Distance from pixel to surrounding coordinates
    
        #Find all the surrounding indices
        outRows = rowKernel + row
        outCols = colKernel + col
    
        #Determine which indices are out of bounds
        inBounds = (outRows >= 0)*(outRows < self._georef_info.ny)*(outCols >= 0)*(outCols < self._georef_info.nx)
        return (outRows[inBounds], outCols[inBounds], dxMults[inBounds])
    
    def _xy_to_rowscols(self, v):
        l = list()
        for (x,y) in v:
            col = round((x-self._georef_info.xllcenter)/self._georef_info.dx)
            row = round((y-self._georef_info.yllcenter)/self._georef_info.dx)
            if col > self._georef_info.nx or row > self._georef_info.ny:
                l.append((None, None))
            else:
                l.append(row,col)
        return tuple(l)
    
    def _rowscols_to_xy(self, l):
        from numpy import float64
        v = list()
        for(row,col) in l:
            x = float64(col)*self._georef_info.dx + self._georef_info_xllcenter
            y = float64(row)*self._georef_info.dx + self._georef_info_yllcenter
            v.append((x,y))
        return tuple(v)
    
    def apply_moving_window(self, moving_window):
        out_grid = None
        out_grid._georef_info = self._georef_info
        out_grid._griddata = moving_window.apply_moving_window(self._griddata, self._georef_info.dx, self.dtype)
        return out_grid
    
    def clip_to_mask_grid(self, mask_grid):
        gdal_source = self._create_gdal_representation_from_array(self._georef_info, 'MEM', self._griddata, self.dtype)
        gdal_mask = mask_grid._create_gdal_representation_from_array(mask_grid._georef_info, 'MEM', mask_grid._griddata, mask_grid.dtype)
        gdal_clip = self._clipRasterToRaster(gdal_source, gdal_mask, self.dtype)
        self._georef_info.geoTransform, self._georef_info.nx, self._georef_info.ny, self._griddata = self._read_GDAL_dataset(gdal_clip, self.dtype)
        self.__populate_georef_info_using_geoTransform(self._georef_info.nx, self._georef_info.ny)

    def clip_to_shapefile(self, shapefile):
        gdal_source = self._create_gdal_representation_from_array(self._georef_info, 'MEM', self._griddata, self.dtype)
        gdal_clip = shapefile.shapedata
        gdal_result = self._clipRasterToShape(gdal_source, gdal_clip)
        self._georef_info.geoTransform, self._georef_info.nx, self._georef_info.ny, self._griddata = self._read_GDAL_dataset(gdal_result, self.dtype)
        self.__populate_georef_info_using_geoTransform(self._georef_info.nx, self._georef_info.ny)
    
    def calculate_gradient_over_length_scale(self,length_scale):
        # sx,sy = calcFiniteDiffs(elevGrid,dx)
        # calculates finite differences in X and Y direction using a finite difference
        # kernel that extends N cells from the center. The width of the kernel is then
        # 2N + 1 by 2N + 1. Applies a boundary condition such that the size and location
        # of the grids in is the same as that out. However, the larger N is, the more NoData
        #Will be around the edges .
    
        #Compute finite differences
        elevGrid = self._griddata
        dx = self._georef_info.dx
        N = np.ceil(length_scale / dx)
        
        Sx = (elevGrid[N:-N, (2*N):] - elevGrid[N:-N, :-(2*N)])/(((2*N)+1)*dx)
        Sy = (elevGrid[(2*N):,N:-N] - elevGrid[:-(2*N), N:-N])/(((2*N)+1)*dx)
    
        #Create two new arrays of the original DEMs size
        SxPadded = np.empty(elevGrid.shape)
        SxPadded[:] = np.NAN
        SyPadded = np.empty(elevGrid.shape)
        SyPadded[:] = np.NAN
    
        SyPadded[N:-N, N:-N] = Sy
        SxPadded[N:-N, N:-N] = Sx
    
        return SxPadded, SyPadded
    
    def calculate_laplacian_over_length_scale(self, length_scale):
        #C = calcFiniteCurv(elevGrid, dx)
        #calculates finite differnces in X and Y direction using the centered difference method.
        #Applies a boundary condition such that the size and location of the grids in is the same as that out.
    
        dx = self._georef_info.dx
        grid = self._griddata
        winRad = np.ceil(length_scale / dx)
        #Assign boundary conditions
        Curv = np.zeros_like(grid)*np.nan
    
        #Compute finite differences
        Cx = (grid[winRad:-winRad, (2*winRad):] - 2*grid[winRad:-winRad, winRad:-winRad] + grid[winRad:-winRad, :-(2*winRad)])/(2*dx*winRad)**2
        Cy = (grid[(2*winRad):, winRad:-winRad] - 2*grid[winRad:-winRad, winRad:-winRad] + grid[:-(2*winRad), winRad:-winRad])/(2*dx*winRad)**2
    
        Curv[winRad:-winRad,winRad:-winRad] = Cx+Cy
        return Curv

class FlowDirection(BaseSpatialGrid):
    pass

class FlowDirectionD8(FlowDirection):
    
    required_inputs_and_actions = ((('nx', 'ny', 'projection', 'geo_transform',),'__create'),
                                   (('ai_ascii_filename','EPSGprojectionCode'),'__read_ai'),
                                   (('gdal_filename',), '__read_gdal'), 
                                   (('flooded_dem',), '__create_from_flooded_dem'))
    
    from numpy import uint8
    dtype = uint8

    def __create_from_flooded_dem(self, *args, **kwargs):
        
    def getFlowToCell(self,i,j):
        #Function to get the indices of the cell that is drained to based on the flow direction specified in fd
            
        iOut = None
        jOut = None
        isGood = False
    
        if self._griddata(i,j) == 1 and j+1 < self._georef_info.nx:
            iOut = i
            jOut = j+1
        elif self._griddata(i,j) == 2 and i+1 < self._georef_info.ny and j+1 < self._georef_info.nx:
            iOut = i+1
            jOut = j+1
        elif self._griddata(i,j) == 4 and i+1 < self._georef_info.ny:
            iOut = i+1
            jOut = j
        elif self._griddata(i,j) == 8 and i+1 < self._georef_info.ny and j-1 >= 0:
            iOut = i+1
            jOut = j-1
        elif self._griddata(i,j) == 16 and j-1 >= 0:
            iOut = i
            jOut = j-1
        elif self._griddata(i,j) == 32 and i-1 >= 0 and j-1 >= 0:
            iOut = i-1
            jOut = j-1
        elif self._griddata(i,j) == 64 and i-1 >= 0:
            iOut = i-1
            jOut = j
        elif self._griddata(i,j) == 128 and i-1 >= 0 and j+1 < self._georef_info.nx:
            iOut = i-1
            jOut = j+1
    
        if not(iOut is None):
            isGood = True
    
        return iOut, jOut, isGood

    def searchDownFlowDirection(self, start):
    
        l = list()
        (row, col) = self._xy_to_rowscols(start)
        l.append((row,col))
        #So long as we are not at the edge of the DEM
        while not (row == 0 or row == self._georef_info.ny-1 or col == 0 or col == self._georef_info.nx - 1):
            # Get the neighbors in the flow direction corresponding order - note, I might be in danger the way I handle this...
            # Flow directions are indices of arrays which may be different sizes, this is not truly giving me flow directions
            # Because in the getNeighbor function I don't return values at edges.... might want to think about improving this,
            # although it should work in this application, and damn if it isn't clean
            row,col,inBounds = self.__getFlowToCell(row, col) # Find the indices of the cell we drain too, only need first two inputs
            if not inBounds:
                break    
            l.append((row, col))
            
        return tuple()

    def convert_rivertools_directions_to_arc(self):
        # Function to convert river tools flow directions to arcGisFlowDirections
          # ArcGIS convention
        # |i-1,j-1  i-1,j  i-1,j+1|  |32 64 128|
        # |i,j-1     i,j     i,j+1|  |16  X  1 |
        # |i+1,j-1  i+1,j  i+1,j+1|  |8   4  2 |
        # In river tools convention the 1 is in the top right
                
        convertedFlowDir = int(np.log2(self._griddata))
        convertedFlowDir -= 1
        convertedFlowDir[convertedFlowDir == -1] = 7
        convertedFlowDir = 2**convertedFlowDir
        convertedFlowDir[self._griddata == self.noData] = self.noData
        self._griddata = convertedFlowDir
        
class Elevation(CalculationMixin, BaseSpatialGrid):
    
    def findDEMedge(self):
        # Function to find the cells at the edge of a dem. Dem is a ny x nx array, but may be largely padded
        # by nans. Determines where the edge of the real data is. Does this by finding the maximum value within a 3x3 kernel,
        # if that is not zero, but the original data at the corresponding location is, then that is an edge cell
            
        #Pad the data so that we can take a windowed max
        padded = np.zeros((self._georef_info.ny+2, self._georef_info.nx+2))
        padded[1:-1, 1:-1] = self._griddata
        padded[padded == 0] = np.nan
    
        # windowMax = np.zeros_like(padded)
        borderCells = np.zeros_like(padded)
    
        #Iterate through all the data, find the max in a 3 x 3 kernel
        for i in range(self._georef_info.ny):
            for j in range(self._georef_info.nx):
                # windowMax[i+1, j+1] = np.nanmax(padded[i:i+3, j:j+3])
                borderCells[i+1, j+1] = np.any(np.isnan(padded[i:i+3, j:j+3]))*(~np.isnan(padded[i+1,j+1]))
    
    
        return np.where(borderCells[1:-1, 1:-1]) # Return edge rows and columns as a tuple

    def calcHillshade(self,az,elev):
        #Hillshade = calcHillshade(elevGrid,az,elev)
        #Esri calculation for generating a hillshade, elevGrid is expected to be a numpy array
    
        # Convert angular measurements to radians
                
        azRad, elevRad = (360 - az + 90)*np.pi/180, (90-elev)*np.pi/180
        Sx, Sy = self._calcFiniteSlopes(self._griddata, self._georef_info.dx)  # Calculate slope in X and Y directions
    
        AspectRad = np.arctan2(Sy, Sx) # Angle of aspect
        SmagRad = np.arctan(np.sqrt(Sx**2 + Sy**2))  # magnitude of slope in radians
    
        return 255.0 * ((np.cos(elevRad) * np.cos(SmagRad)) + (np.sin(elevRad)* np.sin(SmagRad) * np.cos(azRad - AspectRad)))
    
class FilledElevation(CalculationMixin, BaseSpatialGrid):
        
    class priorityQueue:
        #Implements a priority queue using heapq. Python has a priority queue module built in, but it
        # is not stably sorted (meaning that two items who are tied in priority are treated arbitrarily, as opposed to being
        # returned on a first in first out basis). This circumvents that by keeping a count on the items inserted and using that
        # count as a secondary priority
    
        def __init__(self):
            # A counter and the number of items are stored separately to ensure that items remain stably sorted and to
            # keep track of the size of the queue (so that we can check if its empty, which will be useful will iterating
            # through the queue)
            self.__pq = []
            self.__counter = 0
            self.__nItems = 0
    
        def get(self):
            #Remove an item and its priority from the queue
            priority, count, item = heapq.heappop(self.__pq)
            self.__nItems -= 1
            return priority, item
    
        def put(self, priority, item):
            #Add an item to the priority queue
            self.__counter += 1
            self.__nItems += 1
            entry = [priority, self.__counter, item]
            heapq.heappush(self.__pq, entry)
    
        def isEmpty(self):
            return self.__nItems == 0


    def flood(self, aggSlope = 0.0):
        # dem is a numpy array of elevations to be flooded, aggInc is the minimum amount to increment elevations by moving upstream
        # use priority flood algorithm described in  Barnes et al., 2013
        # Priority-Flood: An Optimal Depression-Filling and Watershed-Labeling Algorithm for Digital Elevation Models
        # NOTE: They have another algorithm to make this more efficient, but to use that and a slope makes things more
        # complicated
                            
        priority_queue = FilledElevation.priorityQueue() # priority queue to sort filling operation
    
        #Create a grid to keep track of which cells have been filled
        self._filled_griddata = self._griddata
        
        closed = np.zeros_like(self._filled_griddata)
    
        #Add all the edge cells to the priority queue, mark those cells as draining (not closed)
        edgeRows, edgeCols = self.findDEMedge()
    
        for i in range(len(edgeCols)):
            row, col = edgeRows[i], edgeCols[i]
    
            closed[row, col] = True
            open.put(self._filled_griddata[row, col], [row, col]) # store the indices as a vector of row column, in the priority queue prioritized by the dem value
    
        #While there is anything left in the priority queue, continue to fill holes
        while not open.isEmpty():
            elevation, rowCol = priority_queue.get()
            row, col = rowCol
            neighborRows, neighborCols, dxMults = self._getNeighborIndices(row, col)
            dxs = self._georef_info.dx * dxMults
    
            #Look through the upstream neighbors
            for i in range(len(neighborCols)):
                if not closed[neighborRows[i], neighborCols[i]]:
                    #Do I need to increment(ramp) things or can I leave things flat? I think I can increment b/c my priority queue is stabley sorted
    
                    #If this was a hole (lower than the cell downstream), fill it
                    if self._filled_griddata[neighborRows[i], neighborCols[i]] <= elevation:
                        self._filled_griddata[neighborRows[i], neighborCols[i]] = elevation + aggSlope*dxs[i]
    
                    closed[neighborRows[i], neighborCols[i]] = True
                    priority_queue.put(self._filled_griddata[neighborRows[i], neighborCols[i]], [neighborRows[i], neighborCols[i]])













def mosaicFolder(folderPath, fileSuffix, outfile):
    #This runs the gdal utility gdal_merge on the command line, is mainly here so that I don't have to continue looking
    #up how to actually accomplish this
    #use os to get files, existing gdal functions to merge them
    files = glob.glob1(folderPath, '*'+fileSuffix) # get all the files in the path
    ## Need to use existing gdal_merge.py.... need to check on interpolation options.
    # could also use gdal_warp i think. Should consider whether I care about the possibility of using the c
    #utility...
    argument = ['python', 'gdal_merge.py', '-o', outfile]
    for file in files:
        argument.append(os.path.join(folderPath, file))
    # sys.argv = argv
    subprocess.call(argument)








































def calcD8Area(elevGrid,dx):

    # I am returning area and flowDirections but NOTE!I might be in danger the way I handle this...
    # Flow directions are indices of arrays which may be different sizes, this is not truly giving me flow directions
    # Because in the getNeighbor function I don't return values at edges.... might want to think about improving this,
    # although it should work in this application
    # Calculate the D8 drainage area for the numpy array representing a DEM in elevGrid, assumes that elevGrid has already been filled
    # Assigns BCs to deal with edges - these should be changed to handle flow differently, currently it will not force flow through the edges

    pxlArea = dx**2  # area of a pixel

    idcs = elevGrid.argsort(axis= None)[::-1] # Get the sorted indices of the array in reverse order (e.g. largest first)
    area = pxlArea*np.ones_like(elevGrid)  # All pixels have at least their own area

    [nrows, ncols] = elevGrid.shape  # How big is the BC array? We don't need to do calulate area on the boundarys...
    flowDir = np.zeros_like(elevGrid, dtype=int)

    for idx in idcs:  # Loop through all the data in sorted order
        [i, j] = np.unravel_index(idx, elevGrid.shape)  # Get the row/column indices

        if not np.isnan(elevGrid[i, j]):
            iNeighbs, jNeighbs, dxMults = getNeighborIndices(i, j, nrows, ncols) # Find the actual indices of the neighbors

            #Find the distance to each of the neighbors
            dxs = dx*dxMults

            #Assign the flow direction of the current point
            thisFD,iRel,jRel = assignD8FlowDir(iNeighbs-i, jNeighbs-j, (elevGrid[i, j] - elevGrid[iNeighbs, jNeighbs])/dxs)

            if not np.isnan(thisFD):
                # accumulate current area, downstream area
                flowDir[i,j] = thisFD
                area[i+iRel, j+jRel] += area[i, j]


    return area, flowDir # Return non bc version of area

def calcD8AreaSlope(filledDem,elevGrid,dx):

    # I am returning area and flowDirections but NOTE!I might be in danger the way I handle this...
    # Flow directions are indices of arrays which may be different sizes, this is not truly giving me flow directions
    # Because in the getNeighbor function I don't return values at edges.... might want to think about improving this,
    # although it should work in this application
    # Calculate the D8 drainage area for the numpy array representing a DEM in elevGrid, assumes that elevGrid has already been filled
    # Assigns BCs to deal with edges - these should be changed to handle flow differently, currently it will not force flow through the edges

    pxlArea = dx**2  # area of a pixel

    idcs = filledDem.argsort(axis= None)[::-1] # Get the sorted indices of the array in reverse order (e.g. largest first)
    area = pxlArea*np.ones_like(elevGrid)  # All pixels have at least their own area
    slope = np.ones_like(elevGrid)*np.nan

    [nrows, ncols] = elevGrid.shape  # How big is the BC array? We don't need to do calulate area on the boundarys...
    flowDir = np.zeros_like(elevGrid, dtype=int)

    for idx in idcs:  # Loop through all the data in sorted order
        [i, j] = np.unravel_index(idx, elevGrid.shape)  # Get the row/column indices

        if not np.isnan(elevGrid[i, j]):
            iNeighbs, jNeighbs, dxMults = getNeighborIndices(i, j, nrows, ncols) # Find the actual indices of the neighbors

            #Find the distance to each of the neighbors
            dxs = dx*dxMults

            #Assign the flow direction of the current point
            thisFD,iRel,jRel = assignD8FlowDir(iNeighbs-i, jNeighbs-j, (filledDem[i, j] - filledDem[iNeighbs, jNeighbs])/dxs)

            if not np.isnan(thisFD):
                # accumulate current area, downstream area
                flowDir[i,j] = thisFD
                area[i+iRel, j+jRel] += area[i, j]

                #Calculate slope to downstream cell
                thisDx = np.sqrt((i-iRel)**2 + (j-jRel)**2)*dx
                slope[i,j] = (elevGrid[i,j] - elevGrid[i+iRel, j+jRel])/thisDx


    return area, flowDir, slope # Return non bc version of area


def assignD8FlowDir(iRel,jRel,slopes):
    ## iRel and jRel are the relative indices from the current point to the surrounding points, the slopes of which are
    ## stored in 'slopes'

    #Search kernel for D8 flow routing, the relative indices of each of the 8 points surrounding a pixel, this is
    # ArcGIS convection
    # |i-1,j-1  i-1,j  i-1,j+1|  |32 64 128|
    # |i,j-1     i,j     i,j+1|  |16  X  1 |
    # |i+1,j-1  i+1,j  i+1,j+1|  |8   4  2 |

    idx = np.argmax(slopes)  # Find steepest surrounding slope
    iOut = iRel[idx]
    jOut = jRel[idx] # Find the index of the steepest surrounding slope

    fd = np.nan

    if iOut == 0 and jOut == 1:
        fd = 1
    elif iOut == 1 and jOut == 1:
        fd = 2
    elif iOut == 1 and jOut == 0:
        fd = 4
    elif iOut == 1 and jOut == -1:
        fd = 8
    elif iOut == 0 and jOut == -1:
        fd = 16
    elif iOut == -1 and jOut == -1:
        fd = 32
    elif iOut == -1 and jOut == 0:
        fd = 64
    elif iOut == -1 and jOut == 1:
        fd = 128

    return fd, iOut, jOut

def calcD8SlopeGrid(dem,fdGrid,dx):

    gridShape = dem.shape
    slopes = np.zeros_like(dem)*np.nan #Preallocate with nans

    for i in range(gridShape[0]):
        for j in range(gridShape[1]):
            slopes[i, j] = getD8slope(dem,fdGrid[i,j],dx,i,j,gridShape[0],gridShape[1])

    return slopes

def getD8slope(dem,fd,dx,i,j,nRows,nCols):

    #Function to get the slope cell in the down flow direction
    iOut,jOut,isGood = getFlowToCell(i,j,fd,nRows,nCols)

    if isGood:
        dist = np.sqrt((i-iOut)**2 + (j-jOut)**2)*dx
        return (dem[i, j]-dem[iOut, jOut])/dist
    else:
        return np.nan






