
# standard imports
import datetime
import numpy as np
import pyproj
import os

# local imports
import RAiDER.constants as const
import RAiDER.models.plotWeather as plots
import RAiDER.util as util
from RAiDER.util import robmin, robmax
from RAiDER.interpolator import fillna3D, interp_along_axis


class WeatherModel():
    '''
    Implement a generic weather model for getting estimated SAR delays
    '''
    def __init__(self):
        # Initialize model-specific constants/parameters
        self._k1 = None
        self._k2 = None
        self._k3 = None
        self._humidityType = 'q'
        self._a = []
        self._b = []

        self._lon_res = None
        self._lat_res = None
        self._x_res = None
        self._y_res = None

        self._classname = None 
        self._dataset = None
        self._model_level_type = 'ml'
        self._valid_range = (datetime.date(1900,1,1),) # Tuple of min/max years where data is available. 
        self._lag_time = datetime.timedelta(days =30) # Availability lag time in days

        # Define fixed constants
        self._R_v = 461.524
        self._R_d = 287.053
        self._g0 = const._g0 # gravity constant
        self._zmin = const._ZMIN # minimum integration height
        self._zmax = const._ZREF # max integration height
        self._llaproj = pyproj.Proj(proj='latlong')
        self._ecefproj = pyproj.Proj(proj='geocent')
        self._proj = None

        # setup data structures  
        self._levels = []
        self._xs = np.empty((1, 1, 1)) # Use generic x/y/z instead of lon/lat/height
        self._ys = np.empty((1, 1, 1))
        self._zs = np.empty((1, 1, 1))

        self._lats = None 
        self._lons = None 

        self._p = None
        self._q = None
        self._rh = None
        self._t = None
        self._e = None
        self._wet_refractivity = None
        self._hydrostatic_refractivity = None
        self._svp = None


        
    def __repr__(self):
        string = '\n'
        string += '======Weather Model class object=====\n'
        string += 'Number of points in Lon/Lat = {}/{}\n'.format(*self._p.shape[:2])
        string += 'Total number of grid points (3D): {}\n'.format(np.prod(self._p.shape))
        string += 'Latitude resolution: {}\n'.format(self._lat_res)
        string += 'Longitude resolution: {}\n'.format(self._lon_res)
        string += 'Native projection: {}\n'.format(self._proj)
        string += 'ZMIN: {}\n'.format(self._zmin)
        string += 'ZMAX: {}\n'.format(self._zmax)
        string += 'Minimum/Maximum y: {: 4.2f}/{: 4.2f}\n'\
                  .format(robmin(self._ys), robmax(self._ys))
        string += 'Minimum/Maximum x: {: 4.2f}/{: 4.2f}\n'\
                  .format(robmin(self._xs), robmax(self._xs))
        string += 'Minimum/Maximum zs/heights: {: 10.2f}/{: 10.2f}\n'\
                  .format(robmin(self._zs), robmax(self._zs))
        string += '=====================================\n'
        string += 'k1 = {}\n'.format(self._k1)
        string += 'k2 = {}\n'.format(self._k2)
        string += 'k3 = {}\n'.format(self._k3)
        string += 'Humidity type = {}\n'.format(self._humidityType)
        string += '=====================================\n'
        string += 'Class name: {}\n'.format(self._classname)
        string += 'Dataset: {}\n'.format(self._dataset)
        string += '=====================================\n'
        string += 'A: {}\n'.format(self._a)
        string += 'B: {}\n'.format(self._b)
        return str(string)

    def Model(self):
        return self._Name
    def ModelObj(self):
        return self

    def fetch(self, lats, lons, time, out):
        '''
        Checks the input datetime against the valid date range for the model and then 
        calls the model _fetch routine
        '''
        self.check(time)
        self._fetch(lats, lons, time, out)

    def _fetch(self, lats, lons, time, out):
        '''
        Placeholder method. Should be implemented in each weather model type class
        '''
        pass

    def load(self, *args, outLats = None, outLons = None, **kwargs):
        '''
        Calls the load_weather method. Each model class should define a load_weather 
        method appropriate for that class. 'args' should be one or more filenames. 
        '''
        self.load_weather(*args, **kwargs)
        self._find_e()
        self._get_wet_refractivity()
        self._get_hydro_refractivity() 

        # adjust the grid based on the height data
        self._adjust_grid(lats =outLats, lons=outLons)

    def load_weather(self, filename):
        '''
        Placeholder method. Should be implemented in each weather model type class
        '''
        pass

    def plot(self, plotType = 'pqt', savefig = True):
        '''
        Plotting method. Valid plot types are 'pqt'
        '''
        if plotType=='pqt':
            plot = plots.plot_pqt(self, savefig)
        elif plotType=='wh':
            plot = plots.plot_wh(self, savefig)
        else:
            raise RuntimeError('WeatherModel.plot: No plotType named {}'.format(plotType))
        return plot

    def check(self, time):
        '''
        Checks the time against the lag time and valid date range for the given model type
        '''
        print('Weather model {} is available from {}-{}'.format(self.Model(), self._valid_range[0], self._valid_range[1]))
        if time<self._valid_range[0]:
            raise RuntimeError("Weather model {} is not available at {}".format(self.Model(), time))
        if self._valid_range[1] is not None: 
            if self._valid_range[1]=='Present':
                pass
            elif self._valid_range[1] < time:
                raise RuntimeError("Weather model {} is not available at {}".format(self.Model(), time))
        if time > datetime.datetime.today() - self._lag_time:
            raise RuntimeError("Weather model {} is not available at {}".format(self.Model(), time))
            
    def setLevelType(self, levelType = 'ml'):
        ''' 
        Update the level type to use in fetching data from the weather models
        '''
        self._model_level_type = levelType

    def _convertmb2Pa(self, pres):
        '''
        Convert pressure in millibars to Pascals
        '''
        return 100*pres

    def _get_heights(self, lats, geo_hgt, geo_ht_fill = np.nan):
        '''
        Transform geo heights to actual heights
        '''
        geo_ht_fix = np.where(geo_hgt!= geo_ht_fill, geo_hgt, np.nan)
        self._zs = util._geo_to_ht(lats, geo_ht_fix, self._g0)

    def _find_e(self):
        """Check the type of e-calculation needed"""
        if self._humidityType=='rh':
            self._find_e_from_rh()
        elif self._humidityType=='q':
            self._find_e_from_q()
        else:
            raise RuntimeError('Not a valid humidity type')

    def _find_e_from_q(self):
        """Calculate e, partial pressure of water vapor."""
        self._find_svp()
        # We have q = w/(w + 1), so w = q/(1 - q)
        w = self._q/(1 - self._q)
        self._e = w*self._R_v*(self._p - self._svp)/self._R_d

    def _find_e_from_rh(self):
        """Calculate partial pressure of water vapor."""
        self._find_svp()
        self._e = self._rh/100 * self._svp

    def _get_wet_refractivity(self):
        '''
        Calculate the wet delay from pressure, temperature, and e
        '''
        self._wet_refractivity = self._k2*self._e/self._t+ self._k3*self._e/self._t**2

    def _get_hydro_refractivity(self):
        '''
        Calculate the hydrostatic delay from pressure and temperature
        '''
        self._hydrostatic_refractivity = self._k1*self._p/self._t

    def getWetRefractivity(self):
        return self._wet_refractivity

    def getHydroRefractivity(self):
        return self._hydrostatic_refractivity

    def _adjust_grid(self, lats = None, lons = None):
        '''
        This function pads the weather grid with a level at self._zmin, if 
        it does not already go that low. It also removes levels that are 
        above self._zmax, since they are not needed. 
        '''

        if self._zmin < np.nanmin(self._zs):
            # first add in a new layer at zmin
            new_heights = np.zeros(self._zs.shape[:2]) + self._zmin
            self._zs = np.concatenate(
                       (new_heights[:,:,np.newaxis], self._zs), axis = 2)

            # since xs/ys (or lons/lats) are the same for all z, just add an
            # extra slice to match the new z shape
            self._xs = np.concatenate((self._xs[:,:,0][...,np.newaxis],self._xs), axis = 2)
            self._ys = np.concatenate((self._ys[:,:,0][...,np.newaxis],self._ys), axis = 2)
            self._lons = np.concatenate((self._lons[:,:,0][...,np.newaxis],self._lons), axis = 2)
            self._lats = np.concatenate((self._lats[:,:,0][...,np.newaxis],self._lats), axis = 2)

            # need to extrapolate the other variables down now
            if self._humidityType == 'q':
                self._q=util.padLower(self._q)
            else:
                self._rh=util.padLower(self._rh)

            self._p=util.padLower(self._p)
            self._t=util.padLower(self._t)
            self._e=util.padLower(self._e)
            self._wet_refractivity=util.padLower(self._wet_refractivity)
            self._hydrostatic_refractivity=util.padLower(self._hydrostatic_refractivity)

        if lats is not None:
            in_extent = self._getExtent(lats, lons)
            self_extent = self._getExtent(self._lats, self._lons)
            if self._isOutside(in_extent, self_extent):
                print('Extent of the input lats/lons is: {}'.format(in_extent))
                print('Extent of the weather model is: {}'.format(self_extent))
                raise RuntimeError('The weather model passed does not cover all of the \n \
                                  input points; you need to download a larger area.')
            self._trimExtent(in_extent) 

    def _getExtent(self,lats, lons):
        '''
        get the bounding box around a set of lats/lons
        '''
        return [np.nanmin(lats), np.nanmax(lats), np.nanmin(lons), np.nanmax(lons)]

    def _isOutside(self, extent1, extent2):
        '''
        Determine whether any of extent1  lies outside extent2
        extent1/2 should be a list containing [lower_lat, upper_lat, left_lon, right_lon]
        '''
        t1 = extent1[0] < extent2[0]
        t2 = extent1[1] > extent2[1]
        t3 = extent1[2] < extent2[2]
        t4 = extent1[3] > extent2[3]
        if np.any([t1, t2, t3, t4]):
           return True
        return False

    def _trimExtent(self,extent, _zlevels = None):
        '''
        get the bounding box around a set of lats/lons
        '''
        mask = (self._lats[:,:,0] > extent[0]) & (self._lats[:,:,0] < extent[1]) & \
               (self._lons[:,:,0] > extent[2]) & (self._lons[:,:,0] < extent[3])
        ma1 = np.sum(mask, axis = 1).astype('bool')
        ma2 = np.sum(mask, axis = 0).astype('bool')

        # indices of the part of the grid to keep
        nx, ny, nz = self._xs.shape
        index1 = max(np.arange(len(ma1))[ma1][0] - 2, 0)
        index2 = min(np.arange(len(ma1))[ma1][-1]+ 2, ny)
        index3 = max(np.arange(len(ma2))[ma2][0] - 2, 0)
        index4 = min(np.arange(len(ma2))[ma2][-1]+ 2, nx)

        # subset around points of interest
        self._lons= self._lons[index1:index2,index3:index4,:]
        self._lats= self._lats[index1:index2,index3:index4,...]
        self._xs  = self._xs[index1:index2,index3:index4,:]
        self._ys  = self._ys[index1:index2,index3:index4,...]
        self._zs  = self._zs[index1:index2,index3:index4,...]
        self._p   = self._p[index1:index2,index3:index4,...]
        self._t   = self._t[index1:index2,index3:index4,...]
        self._e   = self._e[index1:index2,index3:index4,...]

        self._wet_refractivity         = self._wet_refractivity[index1:index2,index3:index4,...]
        self._hydrostatic_refractivity = self._hydrostatic_refractivity[index1:index2,index3:index4,:]

        self._uniform_in_z(_zlevels=_zlevels)

    def _find_svp(self):
        """
        Calculate standard vapor presure. Should be model-specific
        """
        # From TRAIN:
        # Could not find the wrf used equation as they appear to be
        # mixed with latent heat etc. Istead I used the equations used
        # in ERA-I (see IFS documentation part 2: Data assimilation
        # (CY25R1)). Calculate saturated water vapour pressure (svp) for
        # water (svpw) using Buck 1881 and for ice (swpi) from Alduchow
        # and Eskridge (1996) euation AERKi
    
        # TODO: figure out the sources of all these magic numbers and move
        # them somewhere more visible.
        # TODO: (Jeremy) - Need to fix/get the equation for the other 
        # weather model types. Right now this will be used for all models, 
        # except WRF, which is yet to be implemented in my new structure.
        t1 = 273.15 # O Celsius
        t2 = 250.15 # -23 Celsius
        
        tref = self._t- t1
        wgt = (self._t - t2)/(t1 - t2)
        svpw = (6.1121 * np.exp((17.502*tref)/(240.97 + tref)))
        svpi = (6.1121 * np.exp((22.587*tref)/(273.86 + tref)))
    
        svp = svpi + (svpw - svpi)*wgt**2
        ix_bound1 =self._t > t1
        svp[ix_bound1] = svpw[ix_bound1]
        ix_bound2 =self._t < t2
        svp[ix_bound2] = svpi[ix_bound2]
    
        self._svp = svp * 100

    
    def _calculategeoh(self, z, lnsp):
        '''
        Function to calculate pressure, geopotential, and geopotential height
        from the surface pressure and model levels provided by a weather model. 
        The model levels are numbered from the highest eleveation to the lowest.
        Inputs: 
            self - weather model object with parameters a, b defined
            z    - 3-D array of surface heights for the location(s) of interest
            lnsp - log of the surface pressure
        Outputs: 
            geopotential - The geopotential in units of height times acceleration
            pressurelvs  - The pressure at each of the model levels for each of 
                           the input points
            geoheight    - The geopotential heights
        ''' 
        geopotential = np.zeros_like(self._t)
        pressurelvs = np.zeros_like(geopotential)
        geoheight = np.zeros_like(geopotential)
    
        # surface pressure: pressure at the surface!
        # Note that we integrate from the ground up, so from the largest model level to 0
        sp = np.exp(lnsp)
    
        # t should be structured [z, y, x]
        levelSize = len(self._levels)

        if len(self._a) != levelSize + 1 or len(self._b) != levelSize + 1:
            raise ValueError(
                'I have here a model with {} levels, but parameters a '.format(levelSize) + 
                'and b have lengths {} and {} respectively. Of '.format(len(self._a),len(self._b)) + 
                'course, these three numbers should be equal.')
    
        Ph_levplusone = self._a[levelSize] + (self._b[levelSize]*sp)
    
        # Integrate up into the atmosphere from *lowest level*
        z_h = 0 # initial value
        for lev, t_level, q_level in zip(
                range(levelSize, 0, -1), self._t[::-1], self._q[::-1]):

            # lev is the level number 1-60, we need a corresponding index
            # into ts and qs
            #ilevel = levelSize - lev # << this was Ray's original, but is a typo 
            # because indexing like that results in pressure and height arrays that 
            # are in the opposite orientation to the t/q arrays. 
            ilevel = lev - 1

            # compute moist temperature
            t_level = t_level*(1 + 0.609133*q_level)
    
            # compute the pressures (on half-levels)
            Ph_lev = self._a[lev-1] + (self._b[lev-1] * sp)
    
            pressurelvs[ilevel] = Ph_lev
    
            if lev == 1:
                dlogP = np.log(Ph_levplusone/0.1)
                alpha = np.log(2)
            else:
                dlogP = np.log(Ph_levplusone/Ph_lev)
                dP = Ph_levplusone - Ph_lev
                alpha = 1 - ((Ph_lev/dP)*dlogP)
    
            TRd = t_level*self._R_d
    
            # z_f is the geopotential of this full level
            # integrate from previous (lower) half-level z_h to the full level
            z_f = z_h + TRd*alpha
            #geoheight[ilevel] = z_f/self._g0

            # Geopotential (add in surface geopotential)
            geopotential[ilevel] = z_f + z
            geoheight[ilevel] = geopotential[ilevel]/self._g0

            # z_h is the geopotential of 'half-levels'
            # integrate z_h to next half level
            z_h += TRd * dlogP

            Ph_levplusone = Ph_lev

        return geopotential, pressurelvs, geoheight

    def _get_ll_bounds(self, lats, lons, Nextra = 2):
        '''
        returns the extents of lat/lon plus a buffer
        '''
        lat_min = np.nanmin(lats) - Nextra*self._lat_res
        lat_max = np.nanmax(lats) + Nextra*self._lat_res
        lon_min = np.nanmin(lons) - Nextra*self._lon_res
        lon_max = np.nanmax(lons) + Nextra*self._lon_res

        return lat_min, lat_max, lon_min, lon_max

    def getProjection(self):
        '''
        Returns the native weather projection, which should be a pyproj object
        '''
        return self._proj

    def getPoints(self):
        return self._xs.copy(),self._ys.copy(), self._zs.copy()
        
    def getLL(self):
        return self._ys[...,0].copy(), self._xs[...,0].copy()

    def getXY_gdal(self, filename):
        '''
        Pull the grid info (x,y) from a gdal-readable file
        '''
        import gdal
        ds = gdal.Open(filename, gdal.GA_ReadOnly)
        xSize, ySize = ds.RasterXSize, ds.RasterYSize
        trans = ds.GetGeoTransform()
        del ds
    
        # make regular point grid
        pixelSizeX = trans[1]
        pixelSizeY = trans[5]
        eastOrigin = trans[0] + 0.5*pixelSizeX
        northOrigin =trans[3] + 0.5*pixelSizeY
        xArray = np.arange(eastOrigin,  eastOrigin + pixelSizeX*xSize,  pixelSizeX)
        yArray = np.arange(northOrigin, northOrigin + pixelSizeY*ySize, pixelSizeY)
    
        return xArray, yArray
        
    def _uniform_in_z(self, _zlevels = None):
        '''
        Interpolate all variables to a regular grid in z
        '''
        nx, ny = self._xs.shape[:2]

        # new regular z-spacing 
        if _zlevels is None:
            _zlevels = np.nanmean(self._zs, axis=(0,1))
        new_zs = np.tile(_zlevels, (nx,ny,1))

        # new variables
        wrf = fillna3D(self._wet_refractivity)
        hrf = fillna3D(self._hydrostatic_refractivity)
        p = fillna3D(self._p)
        t = fillna3D(self._t)
        e = fillna3D(self._e)
        wrf_new = interp_along_axis(self._zs, new_zs, wrf, axis = 2)
        hrf_new = interp_along_axis(self._zs, new_zs, hrf, axis = 2)
        t_new = interp_along_axis(self._zs, new_zs, t, axis = 2)
        p_new = interp_along_axis(self._zs, new_zs, p, axis = 2)
        e_new = interp_along_axis(self._zs, new_zs, e, axis = 2)

        # re-assign values to the uniform z
        self._p = p_new
        self._t = t_new
        self._e = e_new
        self._wet_refractivity = wrf_new
        self._hydrostatic_refractivity = hrf_new
        self._zs = _zlevels
        self._xs = np.unique(self._xs)
        self._ys = np.unique(self._ys)

        self._rh = None
        self._q = None

