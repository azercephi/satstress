"""
Calculate stresses over a rectangular geographic region on a regular
lat-lon-time grid.

L{gridcalc} allows you to specify a grid of times and locations (using a
L{Grid} object) at which to perform stress calculations using the L{satstress}
module.  A L{GridCalc} object is created from a L{StressCalc} object and a
L{Grid} object, and can be saved to disk for visualization and sharing as a
U{Unidata NetCDF data cube <http://www.unidata.ucar.edu/software/netcdf>} (.nc)
file.

"""

import satstress as ss
import re
import time
import netCDF3
import physcon as pc
import numpy
from numpy import linalg
import scipy
from optparse import OptionParser

__NETCDF_CONVENTIONS__ = "None"

def main():
    
    usage = "usage: %prog [options] satfile gridfile outfile" 
    description = __doc__
    op = OptionParser(usage)

    (options, args) = op.parse_args()

    # Do a (very) little error checking on the arguments:
    if len(args) != 3:
        op.error("incorrect number of arguments")

    # The satfile defines the satellite and forcings it is subject to:
    satfile = open(args[0], 'r')
    the_sat = ss.Satellite(satfile)
    satfile.close()

    # The gridfile defines the scope and resolution of the calculation:

    # Note here that we're actually storing information about the satellite in
    # two places: once in the Grid, and once in the StressDef objects that make
    # up the StressCalc object.  This is probably bad - since one could twiddle
    # with the parameters on one place, and not the other, and end up getting
    # apparently bogus output.  Be careful.
    gridfile = open(args[1], 'r')
    the_grid = Grid(gridfile, satellite=the_sat)
    gridfile.close()

    the_stresscalc = ss.StressCalc([ss.NSR(the_sat), ss.Diurnal(the_sat)])
    the_gridcalc = GridCalc(the_grid, the_stresscalc)
    the_gridcalc.write_netcdf(args[2])

class Grid(object): # {{{
    """
    A container class defining the temporal and geographic range and resolution
    of the gridded stress calculation.

    The parameters defining the calculation grid are read in from a name value
    file, parsed into a Python dictionary using L{satstress.nvf2dict}, and used
    to set the data attributes of the L{Grid} object.

    The geographic extent and resolution of the calculation is specified by
    minimum and maximum values for latitude and longitude, as well as the
    number of regularly spaced latitude and longitude values to calcualte in
    total (including the minimum and maximum values).  Similarly, time or
    orbital position are specified by an initial value, a final value, and the
    total number of values the time dimension should take on.  In the input
    name-value file, the names used to specify these grid parameters are:

    LAT_MIN, LAT_MAX, LAT_NUM
    LON_MIN, LON_MAX, LON_NUM

    and only one of the following two temporal parameters:

    TIME_MIN,  TIME_MAX,  TIME_NUM
    ORBIT_MIN, ORBIT_MAX, ORBIT_NUM

    with latitude, longitude, and orbital position being specified in degrees,
    and time being specified in seconds.  Both orbital position and time are
    assumed to be zero at periapse.

    The variability of the NSR stresses are similarly explored by specifying 
    the range and resolution of the NSR_PERIOD using:

    NSR_PERIOD_MIN, NSR_PERIOD_MAX, NSR_PERIOD_NUM

    @ivar grid_id: A string identifying the grid
    @type grid_id: str

    @ivar lat_min: Southern bound, degrees (north positive).
    @type lat_min: float
    @ivar lat_max: Northern bound, degrees (north positive).
    @type lat_max: float
    @ivar lat_num: Number of latitude values in the grid.
    @type lat_num: float

    @ivar lon_min: Western bound, degrees (east positive).
    @type lon_min: float
    @ivar lon_max: Eastern bound, degrees (east positive).
    @type lon_max: float
    @ivar lon_num: Number of longitude values in the grid.
    @type lon_num: float

    @ivar time_min: Initial time at which calculation begins (0 = periapse).
    @type time_min: float
    @ivar time_max: Final time at which calculation ends.
    @type time_max: float
    @ivar time_num: Number of timesteps to calculate.
    @type time_num float

    @ivar orbit_min: Initial orbital position in degrees (0 = periapse)
    @type orbit_min: float
    @ivar orbit_max: Final orbital position in degrees (0 = periapse)
    @type orbit_max: float
    @ivar orbit_num: Number of orbital timesteps to calculate.
    @type orbit_num: float

    @ivar satellite: the satellite whose orbital parameters should be used in
    converting between orbital position and time (if necessary)
    @type satellite: L{satstress.Satellite}

    """

    def __init__(self, gridfile=None, satellite=None):
        """Initialize the Grid object from a gridfile.

        @param gridfile: a name value file specifying a calculation grid
        @type gridfile: file
        @param satellite: the satellite whose orbital parameters should be used
        in converting between orbital position and time (if necessary)
        @type satellite: L{satstress.Satellite}

        @raise MissingDimensionError: if the input gridfile does not specify
        the range and resolution of latitude, longitude, time/orbital position
        and NSR period values to do calculations for.

        """

        assert((gridfile is not None) and (satellite is not None))
        # Slurp up the proffered parameters:
        gridParams = ss.nvf2dict(gridfile, comment='#')

        self.satellite = satellite

        self.grid_id = gridParams['GRID_ID']

        try:
            self.lat_min = float(gridParams['LAT_MIN'])
            self.lat_max = float(gridParams['LAT_MAX'])
            self.lat_num = float(gridParams['LAT_NUM'])
        except KeyError:
            raise MissingDimensionError(gridfile, 'latitude')

        try:
            self.lon_min = float(gridParams['LON_MIN'])
            self.lon_max = float(gridParams['LON_MAX'])
            self.lon_num = float(gridParams['LON_NUM'])
        except KeyError:
            raise MissingDimensionError(gridfile, 'longitude')

        try:
            self.time_min = float(gridParams['TIME_MIN'])
            self.time_max = float(gridParams['TIME_MAX'])
            self.time_num = float(gridParams['TIME_NUM'])
            self.orbit_min = None
            self.orbit_max = None
            self.orbit_num = None
        except KeyError:
            try:
                self.orbit_min = float(gridParams['ORBIT_MIN'])
                self.orbit_max = float(gridParams['ORBIT_MAX'])
                self.orbit_num = float(gridParams['ORBIT_NUM'])
                self.time_min = satellite.orbit_period()*(self.orbit_min/360.0)
                self.time_max = satellite.orbit_period()*(self.orbit_max/360.0)
                self.time_num = satellite.orbit_period()*(self.orbit_num/360.0)
            except KeyError:
                raise MissingDimensionError(gridfile, 'time/orbital position')

        try:
            self.nsr_period_min = float(gridParams['NSR_PERIOD_MIN'])
            self.nsr_period_max = float(gridParams['NSR_PERIOD_MAX'])
            self.nsr_period_num = float(gridParams['NSR_PERIOD_NUM'])
        except KeyError:
            raise MissingDimensionError(gridfile, 'NSR period')

    def __str__(self):
        """Output a grid definition file."""

        # We need to comment out one of the orbit or time variables, so as to
        # avoid having a redundant specification.
        if self.orbit_min is None:
            time_comment = '#'
            orbit_comment = ''
        else:
            time_comment = ''
            orbit_comment = '#'

        myStr = """
# =============================================================================
# A string identifying the grid:
# =============================================================================
GRID_ID = %s

# =============================================================================
# The geographic boundaries of the calculation grid:
# =============================================================================
LAT_MIN = %s
LAT_MAX = %s
LAT_NUM = %s

LON_MIN = %s
LON_MAX = %s
LON_NUM = %s

# =============================================================================
# Temporal range and resolution of the calculation may be specified either in
# terms of orbital position (degrees) or time (seconds) after periapse:
# =============================================================================
%sTIME_MIN = %s
%sTIME_MAX = %s
%sTIME_NUM = %s

%sORBIT_MIN = %s
%sORBIT_MAX = %s
%sORBIT_NUM = %s
        """ % (self.grid_id,\
               self.lat_min, self.lat_max, self.lat_num,\
               self.lon_min, self.lon_max, self.lon_num,\
               time_comment, self.time_min,\
               time_comment, self.time_max,\
               time_comment, self.time_num,\
               orbit_comment, self.orbit_min,\
               orbit_comment, self.orbit_max,\
               orbit_comment, self.orbit_num,)

        myStr += """
# =============================================================================
# 
# =============================================================================
NSR_PERIOD_MIN = %s
NSR_PERIOD_MAX = %s
NSR_PERIOD_NUM = %s
        """ % (self.nsr_period_min, self.nsr_period_max, self.nsr_period_num)
    
#  end class Grid }}}

class GridCalc(object): # {{{
    """
    An object that performs a L{StressCalc} on a regularly spaced L{Grid}.

    A C{GridCalc} object takes a particular L{StressCalc} object and
    instantiates the calculation it embodies at each point in the regularly
    spaced grid specified by the associated L{Grid} object.

    """

    def __init__(self, grid=None, stresscalc=None):
       """
       Set the L{Grid} and L{StressCalc} attributes of the GridCalc object.

       Should eventually allow both of these to be set by simply passing in
       a netCDF file representing a previous SatStress calculation.

       """
       if (grid is not None) and (stresscalc is not None):
           self.grid = grid
           self.stresscalc = stresscalc
       else:
           raise GridCalcInitError()

    def __str__(self):
        """
        Output the name/value pairs required to reconstitute both the
        L{StressCalc} and L{Grid} objects which make up the L{GridCalc} object

        """
        myStr = str(self.satellite)
        myStr += str(self.grid)
        return myStr

    def write_netcdf(self, outfile):
        """
        Output a netCDF file containing the results of the calculation
        specified by the GridCalc object.

        Each stress field encapsulated in the GridCalc object will be output
        within the netCDF file as three data fields, one for each of the stress
        tensor components L{Ttt}_NAME, L{Tpt}_NAME, L{Tpp}_NAME, where NAME is
        the name of the L{StressDef} object (e.g. L{Diurnal} or L{NSR}).

        Writing out the calculation results causes the calculation to take
        place.  No mechanism for performing the calculation and retaining it
        in memory for manipulation is currently provided.

        """

        # Create a netCDF file object to stick the calculation results in:
        nc_out = netCDF3.Dataset(outfile, 'w')

        # Set metadata fields of nc_out appropriate to the calculation at hand.

        nc_out.description = "satstress calculation on a regular grid.  All parameter units are SI (meters-kilograms-seconds)"
        nc_out.history     = """Created: %s using the satstress python package: http://code.google.com/p/satstress""" % ( time.ctime(time.time()) )
        nc_out.Conventions = __NETCDF_CONVENTIONS__

        ########################################################################
        # Independent (input) parameters for the run:
        ########################################################################
        nc_out.grid_id     = self.grid.grid_id
        nc_out.system_id   = self.grid.satellite.system_id
        nc_out.planet_mass = self.grid.satellite.planet_mass
        nc_out.orbit_eccentricity = self.grid.satellite.orbit_eccentricity
        nc_out.orbit_semimajor_axis = self.grid.satellite.orbit_semimajor_axis

        nc_out.layer_id_0    = self.grid.satellite.layers[0].layer_id
        nc_out.density_0     = self.grid.satellite.layers[0].density
        nc_out.lame_mu_0     = self.grid.satellite.layers[0].lame_mu
        nc_out.lame_lambda_0 = self.grid.satellite.layers[0].lame_lambda
        nc_out.thickness_0   = self.grid.satellite.layers[0].thickness
        nc_out.viscosity_0   = self.grid.satellite.layers[0].viscosity
        nc_out.tensile_str_0 = self.grid.satellite.layers[0].tensile_str

        nc_out.layer_id_1    = self.grid.satellite.layers[1].layer_id
        nc_out.density_1     = self.grid.satellite.layers[1].density
        nc_out.lame_mu_1     = self.grid.satellite.layers[1].lame_mu
        nc_out.lame_lambda_1 = self.grid.satellite.layers[1].lame_lambda
        nc_out.thickness_1   = self.grid.satellite.layers[1].thickness
        nc_out.viscosity_1   = self.grid.satellite.layers[1].viscosity
        nc_out.tensile_str_1 = self.grid.satellite.layers[1].tensile_str

        nc_out.layer_id_2    = self.grid.satellite.layers[2].layer_id
        nc_out.density_2     = self.grid.satellite.layers[2].density
        nc_out.lame_mu_2     = self.grid.satellite.layers[2].lame_mu
        nc_out.lame_lambda_2 = self.grid.satellite.layers[2].lame_lambda
        nc_out.thickness_2   = self.grid.satellite.layers[2].thickness
        nc_out.viscosity_2   = self.grid.satellite.layers[2].viscosity
        nc_out.tensile_str_2 = self.grid.satellite.layers[2].tensile_str

        nc_out.layer_id_3    = self.grid.satellite.layers[3].layer_id
        nc_out.density_3     = self.grid.satellite.layers[3].density
        nc_out.lame_mu_3     = self.grid.satellite.layers[3].lame_mu
        nc_out.lame_lambda_3 = self.grid.satellite.layers[3].lame_lambda
        nc_out.thickness_3   = self.grid.satellite.layers[3].thickness
        nc_out.viscosity_3   = self.grid.satellite.layers[3].viscosity
        nc_out.tensile_str_3 = self.grid.satellite.layers[3].tensile_str

        ########################################################################
        # A selection of dependent (output) parameters for the run.
        ########################################################################
        nc_out.satellite_radius          = self.grid.satellite.radius()
        nc_out.satellite_mass            = self.grid.satellite.mass()
        nc_out.satellite_density         = self.grid.satellite.density()
        nc_out.satellite_surface_gravity = self.grid.satellite.surface_gravity()
        nc_out.satellite_orbit_period    = self.grid.satellite.orbit_period()

        ########################################################################
        # What about Frequency dependent Parameters?
        ########################################################################
        # There are a variety of interesting frequency-dependent parameters
        # that we ought to really output as well (delta, and the complex Love
        # numbers, Lame parameters...) for reference, but they'll all depend on
        # exactly which slice (for instance) in NSR we're looking at, so the
        # right place to put this meta-data isn't really in the global section
        # it should be associated with the stress variables themselves.
        #
        # It seems that the right way to do this is to define several 1-d
        # variables that are not coordinate variables (that is, they don't
        # correspond to one of the dimensions, unlike latitude, or longitude)
        # e.g.:
        # nc_out.createVariable('nsr_delta_upper', self.grid.nsr_period_num, ('nsr_period'))
        # nc_out.createVariable('nsr_lame_mu_twiddle', self.grid.nsr_period_num, ('nsr_period'))

        ########################################################################
        # A few parameters pertaining to the web-interface only:
        ########################################################################
        # TODO
        nc_out.ssweb_run_id     = ""
        nc_out.ssweb_username   = ""
        nc_out.ssweb_ip_address = ""


        ########################################################################
        # Specify the size and shape of the output datacube.
        ########################################################################

        # LATITUDE:
        nc_out.createDimension('latitude', self.grid.lat_num)
        lats = nc_out.createVariable('latitude',  'f4', ('latitude',))
        lats.units = "degrees_north"
        lats.long_name = "latitude"
        lats[:] = numpy.linspace(self.grid.lat_min, self.grid.lat_max, self.grid.lat_num)

        # LONGITUDE:
        nc_out.createDimension('longitude', self.grid.lon_num)
        lons = nc_out.createVariable('longitude',  'f4', ('longitude',))
        lons.units = "degrees_east"
        lons.long_name = "longitude"
        lons[:] = numpy.linspace(self.grid.lon_min, self.grid.lon_max, self.grid.lon_num)

        # NSR_PERIOD
        nc_out.createDimension('nsr_period', self.grid.nsr_period_num)
        nsr_periods = nc_out.createVariable('nsr_period', 'f4', ('nsr_period',))
        nsr_periods.units = "seconds"
        nsr_periods.long_name = "NSR period"
        nsr_periods[:] = numpy.logspace(numpy.log10(self.grid.nsr_period_min), numpy.log10(self.grid.nsr_period_max), self.grid.nsr_period_num)

        # TIME:
        # Check to see what kind of units we're using for time, and name the
        # variables and their units appropriately
        if self.grid.orbit_min is None:
            nc_out.createDimension('time', self.grid.time_num)
            times = nc_out.createVariable('time', 'f4', ('time',))
            times.units = "seconds"
            times.long_name = "time after periapse"
            times[:] = numpy.linspace(self.grid.time_min, self.grid.time_max, self.grid.time_num)
        else:
            nc_out.createDimension('time', self.grid.orbit_num)
            times = nc_out.createVariable('time', 'f4', ('time',))
            times.units = "degrees"
            times.long_name = "degrees after periapse"
            times[:] = numpy.linspace(self.grid.orbit_min, self.grid.orbit_max, self.grid.orbit_num)

        # At this point, we should have all the netCDF dimensions and their
        # corresponding coordinate variables created (latitutde, longitude,
        # time/orbit, nsr_period), but we still haven't created the data
        # variables, which will ultimately hold the results of our stress
        # calculation, and which depend on the aforedefined dimensions


        # DIURNAL:
        Ttt_Diurnal = nc_out.createVariable('Ttt_Diurnal', 'f4', ('time', 'latitude', 'longitude',))
        Ttt_Diurnal.units = "Pa"
        Ttt_Diurnal.long_name = "north-south component of Diurnal eccentricity stresses"

        Tpt_Diurnal = nc_out.createVariable('Tpt_Diurnal', 'f4', ('time', 'latitude', 'longitude',))
        Tpt_Diurnal.units = "Pa"
        Tpt_Diurnal.long_name = "shear component of Diurnal eccentricity stresses"

        Tpp_Diurnal = nc_out.createVariable('Tpp_Diurnal', 'f4', ('time', 'latitude', 'longitude',))
        Tpp_Diurnal.units = "Pa"
        Tpp_Diurnal.long_name = "east-west component of Diurnal eccentricity stresses"

        # NSR:
        Ttt_NSR = nc_out.createVariable('Ttt_NSR', 'f4', ('nsr_period', 'latitude', 'longitude',))
        Ttt_NSR.units = "Pa"
        Ttt_NSR.long_name = "north-south component of NSR stresses"

        Tpt_NSR = nc_out.createVariable('Tpt_NSR', 'f4', ('nsr_period', 'latitude', 'longitude',))
        Tpt_NSR.units = "Pa"
        Tpt_NSR.long_name = "shear component of NSR stresses"

        Tpp_NSR = nc_out.createVariable('Tpp_NSR', 'f4', ('nsr_period', 'latitude', 'longitude',))
        Tpp_NSR.units = "Pa"
        Tpp_NSR.long_name = "east-west component of NSR stresses"

        # Get the StressDef objects corresponding to Diurnal and NSR stresses:
        for stress in self.stresscalc.stresses:
            if stress.__name__ is 'Diurnal':
                diurnal_stress = ss.StressCalc([stress,])
            if stress.__name__ is 'NSR':
                nsr_stress = ss.StressCalc([stress,])

        # Loop over the time variable, doing diurnal calculations over an orbit  
        for t in range(len(times[:])):
            # We need some kind of progress update, and we need to make sure that
            # we have a representation of the time coordinate in seconds, because
            # that's what the satstress library expects - even if we're ultimately
            # communicating time to the user in terms of "degrees after periapse"
            if self.grid.orbit_min is None:
                time_sec = times[t]
            else:
                time_sec = diurnal_stress.stresses[0].satellite.orbit_period()*(times[t]/360.0)

            print "Calculating Diurnal stresses at", times[t], times.long_name

            for lon in range(len(lons[:])):
                for lat in range(len(lats[:])):

                    Tau_D = diurnal_stress.tensor(theta = scipy.radians(90.0-lats[lat]),\
                                                    phi = scipy.radians(lons[lon]),\
                                                      t = time_sec )

                    nc_out.variables['Ttt_Diurnal'][t,lat,lon] = Tau_D[0,0]
                    nc_out.variables['Tpt_Diurnal'][t,lat,lon] = Tau_D[1,0]
                    nc_out.variables['Tpp_Diurnal'][t,lat,lon] = Tau_D[1,1] 

        # Make sure everything gets written out to the file.
        nc_out.sync()

        # Change the satellite's eccentricity to zero to exclude the Diurnal
        # stresses for the purposes of calculating the NSR stresses:
        nsr_stress.stresses[0].satellite.orbit_eccentricity = 0.0

        # Loop over all the prescribed values of NSR_PERIOD, and do the NSR stress calculation
        # at each point on the surface.
        for p_nsr in range(len(nsr_periods[:])):
        
            # Adjust the properties of the Satellite and StressDef objects
            # for the nsr_period being considered:
            new_sat = nsr_stress.stresses[0].satellite
            new_sat.nsr_period = nsr_periods[p_nsr]
            nsr_stress = ss.StressCalc([ss.NSR(new_sat),])

            print "Calculating NSR stresses for Pnsr = %g %s" % (nsr_periods[p_nsr], nsr_periods.units,)
            for lon in range(len(lons[:])):
                for lat in range(len(lats[:])):
                    Tau_N = nsr_stress.tensor(theta = scipy.radians(90-lats[lat]),\
                                                phi = scipy.radians(lons[lon]),\
                                                  t = 0 )

                    nc_out.variables['Ttt_NSR'][p_nsr,lat,lon] = Tau_N[0,0]
                    nc_out.variables['Tpt_NSR'][p_nsr,lat,lon] = Tau_N[1,0]
                    nc_out.variables['Tpp_NSR'][p_nsr,lat,lon] = Tau_N[1,1] 

        # Make sure everything gets written out to the file.
        nc_out.sync()

# }}}

class Error(Exception):
    """Base class for errors within the L{gridcalc} module."""
    pass

class GridParamError(Error):
    """Base class for errors in L{Grid} object specifications."""
    pass

class MissingDimensionError(GridParamError):
    """Indicates that no time or orbital location dimension was specified in
    the file defining the calculation grid."""

    def __init__(self, gridfile, missing_dim):
       """Stores the file which failed to specify the time dimension."""
       self.gridfile = gridfile
       self.missing_dim

    def __str__(self):
        return("""
No range of %s values was specified in the calculation grid definition read in
from the file:

%s

Every L{Grid} must contain at least a single time value or orbital position.
""" % (self.missing_dim, self.gridfile.name))

if __name__ == "__main__":
    main()

# What do I actually want the plotting tool to do?
#
# Given a list of netCDF files containing variables Ttt_*, Tpt_*, Tpp_*
# representing the tensor components of the surface membrane stresses:

#  - allow the display of either the magnitude of the tensor component,
#  - or the magnitude and direction of the principal components
#  - of one, or the sum of several, of the stress tensors in the files.

# Assuming that all of the netCDF files given to the tool contain compatible
# grids (the same set of lat/lon points) the user should be able to choose
# within each file amongst the values available for that file's "record"
# dimension (e.g. the time/orbital position dimension for Diurnal)
#
# Ideally, the user would be able to use even grids that don't have the same
# geographic points, so long as they are close enough in density for an
# interpolated grid to be acceptably accurate, but that's gravy, and something
# that would be part of the plotting program, not gridcalc.
