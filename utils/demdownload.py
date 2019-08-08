from osgeo import gdal
import numpy as np
import os
import scipy.interpolate
from scipy.interpolate import RegularGridInterpolator as rgi

import utils.util as util

gdal.UseExceptions()


_world_dem = ('https://cloud.sdsc.edu/v1/AUTH_opentopography/Raster/'
              'SRTM_GL1_Ellip/SRTM_GL1_Ellip_srtm.vrt')


def download_dem(lats, lons, outLoc, save_flag= True, checkDEM = True):
    '''
    Download a DEM if one is not already present. 
    '''
    gdalNDV = 0
    print('Getting the DEM')

    # Insert check for DEM noData values
    if checkDEM:
        lats[lats==0.] = np.nan
        lons[lons==0.] = np.nan

    minlon = np.nanmin(lons) - 0.02
    maxlon = np.nanmax(lons) + 0.02
    minlat = np.nanmin(lats) - 0.02
    maxlat = np.nanmax(lats) + 0.02

    # Make sure the DEM hasn't already been downloaded
    outRasterName = os.path.join(outLoc, 'warpedDEM.dem' \
                                   .format(minlat, maxlat, minlon, maxlon))
 
    if os.path.exists(outRasterName):
       import pdb; pdb.set_trace()
       print('WARNING: DEM already exists in {}, checking extents'.format(outLoc))
       hgts = util.gdal_open(outRasterName)
       if util.isOutside(util.getExtent(lats), util.getExtent(hgts)):
          raise RuntimeError('Existing DEM does not cover the area of the input \n \
                              lat/lon points; either move the DEM, delete it, or \n \
                              change the inputs.')
       hgts[hgts==0.] = np.nan
       return hgts


    # Specify filenames
    outRaster = '/vsimem/warpedDEM'
    inRaster ='/vsicurl/{}'.format(_world_dem) 

    # Download and warp
    print('Beginning DEM download and warping')
    
    wrpOpt = gdal.WarpOptions(outputBounds = (minlon, minlat,maxlon, maxlat))
    gdal.Warp(outRaster, inRaster, options = wrpOpt)

    print('DEM download finished')

    # Load the DEM data
    try:
        out = util.gdal_open(outRaster)
    except:
        raise RuntimeError('demdownload: Cannot open the warped file')
    finally:
        try:
            gdal.Unlink('/vsimem/warpedDEM')
        except:
            pass

    #  Flip the orientation, since GDAL writes top-bot
    out = out[::-1]

    #TODO: do the projection in gdal itself
    print('Beginning interpolation')
    xlats = np.linspace(minlat, maxlat, out.shape[0])
    xlons = np.linspace(minlon, maxlon, out.shape[1])
    interpolator = rgi(points = (xlats, xlons),values = out,
                       method='linear', 
                       bounds_error = False)

    outInterp = interpolator(np.stack((lats, lons), axis=-1))

    # Need to ensure that noData values are consistently handled and 
    # can be passed on to GDAL
    outInterp[np.isnan(outInterp)] = gdalNDV
    outInterp[outInterp < -10000] = gdalNDV

    print('Interpolation finished')

    if save_flag:
        print('Saving DEM to disk')
        if outInterp.ndim==2:
            util.writeArrayToRaster(outInterp, 
                                outRasterName, 
                                noDataValue = gdalNDV)
        elif outInterp.ndim==1:
            util.writeArrayToFile(lons, lats, outInterp, outRasterName, noDataValue = -9999)
        else:
            import pdb; pdb.set_trace()
        print('Finished saving DEM to disk')

    return outInterp
