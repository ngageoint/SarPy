# -*- coding: utf-8 -*-
"""
The GridType definition.
"""

import logging

import numpy
from numpy.linalg import norm
from scipy.optimize import newton
from scipy.constants import speed_of_light

from .base import Serializable, DEFAULT_STRICT, \
    _StringDescriptor, _StringEnumDescriptor, _FloatDescriptor, _FloatArrayDescriptor, \
    _IntegerEnumDescriptor, _SerializableDescriptor, _UnitVectorDescriptor, \
    _ParametersDescriptor, ParametersCollection
from .blocks import XYZType, Poly2DType


__classification__ = "UNCLASSIFIED"

# module variable
DEFAULT_WEIGHT_SIZE = 512
"""
int: the default size when generating WgtFunct from a named WgtType.
"""


def _hamming_ipr(x, a):  # TODO: what is a? This name stinks.
    """Helper method"""
    return a*numpy.sinc(x) + (1-a)*(numpy.sinc(x-1) + numpy.sinc(x+1)) - a/numpy.sqrt(2)


def _raised_cos(n, coef):  # TODO: This name also stinks
    """Helper method"""
    weights = numpy.zeros((n,), dtype=numpy.float64)
    if (n % 2) == 0:
        theta = 2*numpy.pi*numpy.arange(n/2)/(n-1)  # TODO: why n-1?
        weights[:n] = (coef - (1-coef)*numpy.cos(theta))
        weights[:n] = weights[:n]
    else:
        theta = 2*numpy.pi*numpy.arange((n+1)/2)/(n-1)
        weights[:n+1] = (coef - (1-coef)*numpy.cos(theta))
        weights[:n+1] = weights[:n]
    return weights


def _taylor_win(n, sidelobes=4, max_sidelobe_level=-30, normalize=True):  # TODO: This name stinks
    """
    Generates a Taylor Window as an array of a given size.

    *From mathworks documentation* - Taylor windows are similar to Chebyshev windows. A Chebyshev window
    has the narrowest possible mainlobe for a specified sidelobe level, but a Taylor window allows you to
    make tradeoffs between the mainlobe width and the sidelobe level. The Taylor distribution avoids edge
    discontinuities, so Taylor window sidelobes decrease monotonically. Taylor window coefficients are not
    normalized. Taylor windows are typically used in radar applications, such as weighting synthetic aperture
    radar images and antenna design.

    Parameters
    ----------
    n : int
        size of the generated window

    sidelobes : int
        Number of nearly constant-level sidelobes adjacent to the mainlobe, specified as a positive integer.
        These sidelobes are "nearly constant level" because some decay occurs in the transition region.

    max_sidelobe_level : float
        Maximum sidelobe level relative to mainlobe peak, specified as a real negative scalar in dB. It produces
        sidelobes with peaks `max_sidelobe_level` *dB* down below the mainlobe peak.

    normalize : bool
        Should the output be normalized so that th max weight is 1?

    Returns
    -------
    numpy.ndarray
        the generated window
    """

    a = numpy.arccosh(10**(-max_sidelobe_level/20.))/numpy.pi
    # Taylor pulse widening (dilation) factor
    sp2 = (sidelobes*sidelobes)/(a*a + (sidelobes-0.5)*(sidelobes-0.5))
    # the angular space in n points
    xi = numpy.linspace(-numpy.pi, numpy.pi, n)
    # calculate the cosine weights
    out = numpy.ones((n, ), dtype=numpy.float64)  # the "constant" term
    coefs = numpy.arange(1, sidelobes)
    sgn = 1
    for m in coefs:
        coefs1 = (coefs - 0.5)
        coefs2 = coefs[coefs != m]  # TODO: why does this have a term removed?
        numerator = numpy.prod(1 - (m*m)/(sp2*(a*a + coefs1*coefs1)))
        denominator = numpy.prod(1 - (m*m)/(coefs2*coefs2))
        out += sgn*(numerator/denominator)*numpy.cos(m*xi)
        sgn *= -1
    if normalize:
        out /= numpy.amax(out)
    return out


class WgtTypeType(Serializable):
    """The weight type parameters of the direction parameters"""
    _fields = ('WindowName', 'Parameters')
    _required = ('WindowName',)
    _collections_tags = {'Parameters': {'array': False, 'child_tag': 'Parameter'}}
    # descriptors
    WindowName = _StringDescriptor(
        'WindowName', _required, strict=DEFAULT_STRICT,
        docstring='Type of aperture weighting applied in the spatial frequency domain (Krow) to yield '
                  'the impulse response in the row direction. '
                  '*Example values - "UNIFORM", "TAYLOR", "UNKNOWN", "HAMMING"*')  # type: str
    Parameters = _ParametersDescriptor(
        'Parameters', _collections_tags, required=_required, strict=DEFAULT_STRICT,
        docstring='Free form parameters list.')  # type: ParametersCollection

    def __init__(self, WindowName=None, Parameters=None, **kwargs):
        """

        Parameters
        ----------
        WindowName : str
        Parameters : ParametersCollection|dict
        kwargs : dict
        """
        self.WindowName = WindowName
        self.Parameters = Parameters
        super(WgtTypeType, self).__init__(**kwargs)

    def get_parameter_value(self, param_name, default=None):
        """
        Gets the value (first value found) associated with a given parameter name.
        Returns `default` if not found.

        Parameters
        ----------
        param_name : str
            the parameter name for which to search.
        default : None|str
            the default value to return if lookup fails.

        Returns
        -------
        str
            the associated parameter value, or `default`.
        """

        if self.Parameters is None:
            return default
        the_dict = self.Parameters.get_collection()
        if len(the_dict) == 0:
            return default
        if param_name is None:
            # get the first value - this is dumb, but appears a use case. Leaving undocumented.
            return the_dict.values()[0]
        return the_dict.get(param_name, default)

    @classmethod
    def from_node(cls, node, kwargs=None):
        if node.find('WindowName') is None:
            # SICD 0.4 standard compliance, this could just be a space delimited string of the form
            #   "<WindowName> <name1>=<value1> <name2>=<value2> ..."
            if kwargs is None:
                kwargs = {}
            values = node.text.strip().split()
            kwargs['WindowName'] = values[0]
            params = {}
            for entry in values[1:]:
                try:
                    name, val = entry.split('=')
                    params[name] = val
                except ValueError:
                    continue
            kwargs['Parameters'] = params
            return cls.from_dict(kwargs)
        else:
            return super(WgtTypeType, cls).from_node(node, kwargs)


class DirParamType(Serializable):
    """The direction parameters container"""
    _fields = (
        'UVectECF', 'SS', 'ImpRespWid', 'Sgn', 'ImpRespBW', 'KCtr', 'DeltaK1', 'DeltaK2', 'DeltaKCOAPoly',
        'WgtType', 'WgtFunct')
    _required = ('UVectECF', 'SS', 'ImpRespWid', 'Sgn', 'ImpRespBW', 'KCtr', 'DeltaK1', 'DeltaK2')
    _numeric_format = {
        'SS': '0.10G', 'ImpRespWid': '0.10G', 'Sgn': '+d', 'ImpRespBW': '0.10G', 'KCtr': '0.10G',
        'DeltaK1': '0.10G', 'DeltaK2': '0.10G', 'WgtFunct': '0.10G'}
    _collections_tags = {'WgtFunct': {'array': True, 'child_tag': 'Wgt'}}
    # descriptors
    UVectECF = _UnitVectorDescriptor(
        'UVectECF', XYZType, required=_required, strict=DEFAULT_STRICT,
        docstring='Unit vector in the increasing (row/col) direction (ECF) at the SCP pixel.')  # type: XYZType
    SS = _FloatDescriptor(
        'SS', _required, strict=DEFAULT_STRICT,
        docstring='Sample spacing in the increasing (row/col) direction. Precise spacing at the SCP.')  # type: float
    ImpRespWid = _FloatDescriptor(
        'ImpRespWid', _required, strict=DEFAULT_STRICT,
        docstring='Half power impulse response width in the increasing (row/col) direction. '
                  'Measured at the scene center point.')  # type: float
    Sgn = _IntegerEnumDescriptor(
        'Sgn', (1, -1), _required, strict=DEFAULT_STRICT,
        docstring='Sign for exponent in the DFT to transform the (row/col) dimension to '
                  'spatial frequency dimension.')  # type: int
    ImpRespBW = _FloatDescriptor(
        'ImpRespBW', _required, strict=DEFAULT_STRICT,
        docstring='Spatial bandwidth in (row/col) used to form the impulse response in the (row/col) direction. '
                  'Measured at the center of support for the SCP.')  # type: float
    KCtr = _FloatDescriptor(
        'KCtr', _required, strict=DEFAULT_STRICT,
        docstring='Center spatial frequency in the given dimension. '
                  'Corresponds to the zero frequency of the DFT in the given (row/col) direction.')  # type: float
    DeltaK1 = _FloatDescriptor(
        'DeltaK1', _required, strict=DEFAULT_STRICT,
        docstring='Minimum (row/col) offset from KCtr of the spatial frequency support for the image.')  # type: float
    DeltaK2 = _FloatDescriptor(
        'DeltaK2', _required, strict=DEFAULT_STRICT,
        docstring='Maximum (row/col) offset from KCtr of the spatial frequency support for the image.')  # type: float
    DeltaKCOAPoly = _SerializableDescriptor(
        'DeltaKCOAPoly', Poly2DType, _required, strict=DEFAULT_STRICT,
        docstring='Offset from KCtr of the center of support in the given (row/col) spatial frequency. '
                  'The polynomial is a function of image given (row/col) coordinate (variable 1) and '
                  'column coordinate (variable 2).')  # type: Poly2DType
    WgtType = _SerializableDescriptor(
        'WgtType', WgtTypeType, _required, strict=DEFAULT_STRICT,
        docstring='Parameters describing aperture weighting type applied in the spatial frequency domain '
                  'to yield the impulse response in the given(row/col) direction.')  # type: WgtTypeType
    WgtFunct = _FloatArrayDescriptor(
        'WgtFunct', _collections_tags, _required, strict=DEFAULT_STRICT, minimum_length=2,
        docstring='Sampled aperture amplitude weighting function (array) applied to form the SCP impulse '
                  'response in the given (row/col) direction.')  # type: numpy.ndarray

    def __init__(self, UVectECF=None, SS=None, ImpRespWid=None, Sgn=None, ImpRespBW=None,
                 KCtr=None, DeltaK1=None, DeltaK2=None, DeltaKCOAPoly=None,
                 WgtType=None, WgtFunct=None, **kwargs):
        """

        Parameters
        ----------
        UVectECF : XYZType|numpy.ndarray|list|tuple
        SS : float
        ImpRespWid : float
        Sgn : int
        ImpRespBW : float
        KCtr : float
        DeltaK1 : float
        DeltaK2 : float
        DeltaKCOAPoly : Poly2DType|numpy.ndarray|list|tuple
        WgtType : WgtTypeType
        WgtFunct : numpy.ndarray|list|tuple
        kwargs : dict
        """
        self.UVectECF = UVectECF
        self.SS = SS
        self.ImpRespWid, self.ImpRespBW = ImpRespWid, ImpRespBW
        self.Sgn = Sgn
        self.KCtr, self.DeltaK1, self.DeltaK2 = KCtr, DeltaK1, DeltaK2
        self.DeltaKCOAPoly = DeltaKCOAPoly
        self.WgtType = WgtType
        self.WgtFunct = WgtFunct
        super(DirParamType, self).__init__(**kwargs)

    def define_weight_function(self, weight_size=DEFAULT_WEIGHT_SIZE):
        """
        Try to derive WgtFunct from WgtType, if necessary. This should likely be called from the `GridType` parent.

        Parameters
        ----------
        weight_size : int
            the size of the WgtFunct to generate.

        Returns
        -------
        None
        """

        if self.WgtType is None or self.WgtType.WindowName is None:
            return  # nothing to be done
        # TODO: should we proceed is WgtFunct is already defined? Should we serialize WgtFunct if WgtType is given?

        window_name = self.WgtType.WindowName.upper()
        if window_name == 'HAMMING':
            # A Hamming window is defined in many places as a raised cosine of weight .54, so this is the default.
            # Some data use a generalized raised cosine and call it HAMMING, so we allow for both uses.
            try:
                # noinspection PyTypeChecker
                coef = float(self.WgtType.get_parameter_value(None, 0.54))  # just get first parameter - name?
            except ValueError:
                coef = 0.54
            self.WgtFunct = _raised_cos(weight_size, coef)
        elif window_name == 'HANNING':
            self.WgtFunct = _raised_cos(weight_size, 0.5)
        elif window_name == 'KAISER':
            try:
                # noinspection PyTypeChecker
                beta = float(self.WgtType.get_parameter_value(None, 14))  # just get first parameter - name?
            except ValueError:
                beta = 14.0  # default suggested in numpy.kaiser
            self.WgtFunct = numpy.kaiser(weight_size, beta)
        elif window_name == 'TAYLOR':
            # noinspection PyTypeChecker
            sidelobes = int(self.WgtType.get_parameter_value('NBAR', 4))  # apparently the matlab argument name
            # noinspection PyTypeChecker
            max_sidelobe_level = float(self.WgtType.get_parameter_value('SLL', -30))  # same
            if max_sidelobe_level > 0:
                max_sidelobe_level *= -1
            self.WgtFunct = _taylor_win(weight_size,
                                        sidelobes=sidelobes,
                                        max_sidelobe_level=max_sidelobe_level,
                                        normalize=True)

    def _get_broadening_factor(self):
        """
        Gets the *broadening factor*, assuming that `WgtFunct` has been properly populated.

        Returns
        -------
        float
            the broadening factor
        """
        # TODO: CLARIFY - what is this?

        if self.WgtFunct is None:
            return None  # nothing to be done

        if self.WgtType is not None and self.WgtType.WindowName is not None:
            window_name = self.WgtType.WindowName.upper()
            coef = None
            if window_name == 'UNIFORM':
                coef = 1.0
            elif window_name == 'HAMMING':
                try:
                    # noinspection PyTypeChecker
                    coef = float(self.WgtType.get_parameter_value(None, 0.54))  # just get first parameter - name?
                except ValueError:
                    coef = 0.54
            elif window_name == 'HANNING':
                coef = 0.5
            if coef is not None:
                return 2 * newton(_hamming_ipr, 0.1, args=(coef,), tol=1e-12, maxiter=10000)

        # solve for the half-power point in an oversampled impulse response
        OVERSAMPLE = 1024
        impulse_response = numpy.absolute(
            numpy.fft.fft(self.WgtFunct, self.WgtFunct.size*OVERSAMPLE))/numpy.sum(self.WgtFunct)
        ind = numpy.flatnonzero(impulse_response < 1/numpy.sqrt(2))[0]  # find first index with less than half power.
        # linearly interpolate between impulse_response[ind-1] and impulse_response[ind] to find 1/sqrt(2)
        v0 = impulse_response[ind-1]
        v1 = impulse_response[ind]
        return 2*(ind + (1./numpy.sqrt(2) - v0)/v1)/OVERSAMPLE

    def define_response_widths(self):
        """
        Assuming that `WgtFunct` has been properly populated, define the response widths.
        This should likely be called by `GridType` parent.

        Returns
        -------
        None
        """

        if self.ImpRespBW is not None and self.ImpRespWid is None:
            broadening_factor = self._get_broadening_factor()
            if broadening_factor is not None:
                self.ImpRespWid = broadening_factor/self.ImpRespBW
        elif self.ImpRespBW is None and self.ImpRespWid is not None:
            broadening_factor = self._get_broadening_factor()
            if broadening_factor is not None:
                self.ImpRespBW = broadening_factor/self.ImpRespWid

    def estimate_deltak(self, valid_vertices):
        """
        The `DeltaK1` and `DeltaK2` parameters can be estimated from `DeltaKCOAPoly`, if necessary. This should likely
        be called by the `GridType` parent.

        Parameters
        ----------
        valid_vertices : None|numpy.ndarray
            The array of corner points.

        Returns
        -------
        None
        """

        if self.DeltaK1 is not None and self.DeltaK2 is not None:
            return  # nothing needs to be done

        if self.ImpRespBW is None or self.SS is None:
            return  # nothing can be done

        if self.DeltaKCOAPoly is not None and valid_vertices is not None:
            deltaKs = self.DeltaKCOAPoly(valid_vertices[0, :], valid_vertices[1, :])
            min_deltak = numpy.amin(deltaKs) - 0.5*self.ImpRespBW
            max_deltak = numpy.amax(deltaKs) - 0.5*self.ImpRespBW
        else:
            min_deltak = max_deltak = -0.5*self.ImpRespBW
        # wrapped spectrum (TLM - what does that mean?)
        if (min_deltak < -0.5/self.SS) or (max_deltak > 0.5/self.SS):
            min_deltak = -0.5/self.SS
            max_deltak = -min_deltak
        self.DeltaK1 = min_deltak
        self.DeltaK2 = max_deltak

    def _basic_validity_check(self):
        condition = super(DirParamType, self)._basic_validity_check()
        if (self.WgtFunct is not None) and (self.WgtFunct.size < 2):
            logging.error(
                'The WgtFunct array has been defined in DirParamType, but there are fewer than 2 entries.')
            condition = False
        return condition


class GridType(Serializable):
    """Collection grid details container"""
    _fields = ('ImagePlane', 'Type', 'TimeCOAPoly', 'Row', 'Col')
    _required = _fields
    _IMAGE_PLANE_VALUES = ('SLANT', 'GROUND', 'OTHER')
    _TYPE_VALUES = ('RGAZIM', 'RGZERO', 'XRGYCR', 'XCTYAT', 'PLANE')
    # descriptors
    ImagePlane = _StringEnumDescriptor(
        'ImagePlane', _IMAGE_PLANE_VALUES, _required, strict=DEFAULT_STRICT,
        docstring="Defines the type of image plane that the best describes the sample grid. Precise plane "
                  "defined by Row Direction and Column Direction unit vectors.")  # type: str
    Type = _StringEnumDescriptor(
        'Type', _TYPE_VALUES, _required, strict=DEFAULT_STRICT,
        docstring="""
        Defines the type of spatial sampling grid represented by the image sample grid. 
        Row coordinate first, column coordinate second:

        * `RGAZIM` - Grid for a simple range, Doppler image. Also, the natural grid for images formed with the Polar 
          Format Algorithm.

        * `RGZERO` - A grid for images formed with the Range Migration Algorithm. Used only for imaging near closest 
          approach (i.e. near zero Doppler).

        * `XRGYCR` - Orthogonal slant plane grid oriented range and cross range relative to the ARP at a 
          reference time.

        * `XCTYAT` - Orthogonal slant plane grid with X oriented cross track.

        * `PLANE` - Arbitrary plane with orientation other than the specific `XRGYCR` or `XCTYAT`.
        \n\n
        """)  # type: str
    TimeCOAPoly = _SerializableDescriptor(
        'TimeCOAPoly', Poly2DType, _required, strict=DEFAULT_STRICT,
        docstring="*Time of Center Of Aperture* as a polynomial function of image coordinates. "
                  "The polynomial is a function of image row coordinate (variable 1) and column coordinate "
                  "(variable 2).")  # type: Poly2DType
    Row = _SerializableDescriptor(
        'Row', DirParamType, _required, strict=DEFAULT_STRICT,
        docstring="Row direction parameters.")  # type: DirParamType
    Col = _SerializableDescriptor(
        'Col', DirParamType, _required, strict=DEFAULT_STRICT,
        docstring="Column direction parameters.")  # type: DirParamType

    def __init__(self, ImagePlane=None, Type=None, TimeCOAPoly=None, Row=None, Col=None, **kwargs):
        """

        Parameters
        ----------
        ImagePlane : str
        Type : str
        TimeCOAPoly : Poly2DType|numpy.ndarray|list|tuple
        Row : DirParamType
        Col : DirParamType
        kwargs : dict
        """
        self.ImagePlane = ImagePlane
        self.Type = Type
        self.TimeCOAPoly = TimeCOAPoly
        self.Row, self.Col = Row, Col
        super(GridType, self).__init__(**kwargs)

    def _derive_direction_params(self, ImageData):
        """
        Populate the Row/Col direction parameters from imageData, if necessary.
        Expected to be called from SICD parent.

        Parameters
        ----------
        ImageData : sarpy.sicd_elements.ImageDataType

        Returns
        -------
        None
        """

        valid_vertices = None
        if ImageData is not None:
            valid_vertices = ImageData.get_valid_vertex_data()
            if valid_vertices is None:
                valid_vertices = ImageData.get_full_vertex_data()

        for attribute in ['Row', 'Col']:
            value = getattr(self, attribute, None)
            if value is not None:
                value.define_weight_function()
                value.define_response_widths()
                value.estimate_deltak(valid_vertices)

    def _derive_time_coa_poly(self, CollectionInfo, SCPCOA):
        """
        Expected to be called from SICD parent.

        Parameters
        ----------
        CollectionInfo : sarpy.sicd_elements.CollectionInfoType
        SCPCOA : sarpy.sicd_elements.SCPCOAType

        Returns
        -------
        None
        """
        if self.TimeCOAPoly is not None:
            return  # nothing needs to be done

        try:
            if CollectionInfo.RadarMode.ModeType == 'SPOTLIGHT':
                self.TimeCOAPoly = Poly2DType(Coefs=[[SCPCOA.SCPTime, ], ])
        except (AttributeError, ValueError):
            return

    @staticmethod
    def _get_center_frequency(RadarCollection, ImageFormation):
        """
        Helper method.

        Parameters
        ----------
        RadarCollection : sarpy.sicd_elements.RadarCollectionType
        ImageFormation : sarpy.sicd_elements.ImageFormationType

        Returns
        -------
        None|float
            The center processed frequency, in the event that RadarCollection.RefFreqIndex is None or 0.
        """

        if RadarCollection is None or RadarCollection.RefFreqIndex is None or RadarCollection.RefFreqIndex == 0:
            return None
        if ImageFormation is None or ImageFormation.TxFrequencyProc is None or \
                ImageFormation.TxFrequencyProc.MinProc is None or ImageFormation.TxFrequencyProc.MaxProc is None:
            return None
        return 0.5*(ImageFormation.TxFrequencyProc.MinProc + ImageFormation.TxFrequencyProc.MaxProc)

    def _derive_rg_az_comp(self, GeoData, SCPCOA, RadarCollection, ImageFormation):
        """
        Expected to be called by SICD parent.

        Parameters
        ----------
        GeoData : sarpy.sicd_elements.GeoDataType
        SCPCOA : sarpy.sicd_elements.SCPCOAType
        RadarCollection : sarpy.sicd_elements.RadarCollectionType
        ImageFormation : sarpy.sicd_elements.ImageFormationType

        Returns
        -------
        None
        """

        if self.Row is None:
            self.Row = DirParamType()
        if self.Col is None:
            self.Col = DirParamType()

        if self.ImagePlane is None:
            self.ImagePlane = 'SLANT'
        elif self.ImagePlane != 'SLANT':
            logging.warning(
                'The Grid.ImagePlane is set to {}, but Image Formation Algorithm is RgAzComp, '
                'which requires "SLANT". resetting.'.format(self.ImagePlane))
            self.ImagePlane = 'SLANT'

        if self.Type is None:
            self.Type = 'RGAZIM'
        elif self.Type != 'RGAZIM':
            logging.warning(
                'The Grid.Type is set to {}, but Image Formation Algorithm is RgAzComp, '
                'which requires "RGAZIM". resetting.'.format(self.Type))

        if GeoData is not None and GeoData.SCP is not None and GeoData.SCP.ECF is not None and \
                SCPCOA.ARPPos is not None and SCPCOA.ARPVel is not None:
            SCP = GeoData.SCP.ECF.get_array()
            ARP = SCPCOA.ARPPos.get_array()
            LOS = (SCP - ARP)
            uLOS = LOS/norm(LOS)
            if self.Row.UVectECF is None:
                self.Row.UVectECF = XYZType.from_array(uLOS)

            look = SCPCOA.look
            ARP_vel = SCPCOA.ARPVel.get_array()
            uSPZ = look*numpy.cross(ARP_vel, uLOS)
            uSPZ /= norm(uSPZ)
            uAZ = numpy.cross(uSPZ, uLOS)
            if self.Col.UVectECF is None:
                self.Col.UVectECF = XYZType.from_array(uAZ)

        center_frequency = self._get_center_frequency(RadarCollection, ImageFormation)
        if center_frequency is not None:
            if self.Row.KCtr is None:
                kctr = 2*center_frequency/speed_of_light
                if self.Row.DeltaKCOAPoly is not None:  # assume it's 0 otherwise?
                    kctr -= self.Row.DeltaKCOAPoly.Coefs[0, 0]
                self.Row.KCtr = kctr
            elif self.Row.DeltaKCOAPoly is None:
                self.Row.DeltaKCOAPoly = Poly2DType(Coefs=[[2*center_frequency/speed_of_light - self.Row.KCtr, ], ])

            if self.Col.KCtr is None:
                if self.Col.DeltaKCOAPoly is not None:
                    self.Col.KCtr = -self.Col.DeltaKCOAPoly.Coefs[0, 0]
            elif self.Col.DeltaKCOAPoly is None:
                self.Col.DeltaKCOAPoly = Poly2DType(Coefs=[[-self.Col.KCtr, ], ])

    def _derive_pfa(self, SCPCOA, RadarCollection, ImageFormation, Position, PFA):
        """
        Expected to be called by SICD parent.

        Parameters
        ----------
        SCPCOA : sarpy.sicd_elements.SCPCOAType
        RadarCollection : sarpy.sicd_elements.RadarCollectionType
        ImageFormation : sarpy.sicd_elements.ImageFormationType
        Position : sarpy.sicd_elements.PositionType
        PFA : sarpy.sicd_elements.PFAType

        Returns
        -------
        None
        """

        if PFA is None:
            return  # nothing to be done

        if self.Type is None:
            self.Type = 'RGAZIM'  # the natural result for PFA

        if SCPCOA.ARPPos is None:
            return

        SCP = SCPCOA.ARPPos.get_array()

        if Position is not None and Position.ARPPoly is not None and PFA.PolarAngRefTime is not None:
            polar_ref_pos = Position.ARPPoly(PFA.PolarAngRefTime)
        else:
            polar_ref_pos = SCP

        if PFA.IPN is not None and PFA.FPN is not None and \
                self.Row.UVectECF is None and self.Col.UVectECF is None:
            ipn = PFA.IPN.get_array()
            fpn = PFA.FPN.get_array()

            dist = numpy.dot((SCP - polar_ref_pos), ipn) / numpy.dot(fpn, ipn)
            ref_pos_ipn = polar_ref_pos + (dist * fpn)
            uRG = SCP - ref_pos_ipn
            uRG /= norm(uRG)
            uAZ = numpy.cross(ipn, uRG)  # already unit
            self.Row.UVectECF = XYZType.from_array(uRG)
            self.Col.UVectECF = XYZType.from_array(uAZ)
        if self.Col is not None and self.Col.KCtr is None:
            self.Col.KCtr = 0  # almost always 0 for PFA

        if self.Row is not None and self.Row.KCtr is None:
            center_frequency = self._get_center_frequency(RadarCollection, ImageFormation)
            if PFA.Krg1 is not None and PFA.Krg2 is not None:
                self.Row.KCtr = 0.5*(PFA.Krg1 + PFA.Krg2)
            elif center_frequency is not None and PFA.SpatialFreqSFPoly is not None:
                # APPROXIMATION: may not be quite right, due to rectangular inscription loss in PFA.
                self.Row.KCtr = 2*center_frequency/speed_of_light + PFA.SpatialFreqSFPoly.Coefs[0]

    def _derive_rma(self, RMA, SCPCOA, RadarCollection, ImageFormation, Position):
        """

        Parameters
        ----------
        RMA : sarpy.sicd_elements.RMAType
        SCPCOA : sarpy.sicd_elements.SCPCOAType
        RadarCollection : sarpy.sicd_elements.RadarCollectionType
        ImageFormation : sarpy.sicd_elements.ImageFormationType
        Position : sarpy.sicd_elements.PositionType

        Returns
        -------
        None
        """

        if RMA is None:
            return   # nothing can be derived

        im_type = RMA.ImageType
        if im_type is None:
            return
        if im_type == 'RMAT':
            self._derive_rma_rmat(RMA, SCPCOA, RadarCollection, ImageFormation)
        elif im_type == 'RMCR':
            self._derive_rma_rmcr(RMA, SCPCOA, RadarCollection, ImageFormation)
        else:
            self._derive_rma_inca(RMA, SCPCOA, Position)

    def _derive_rma_rmat(self, RMA, SCPCOA, RadarCollection, ImageFormation):
        """

        Parameters
        ----------
        RMA : sarpy.sicd_elements.RMAType
        SCPCOA : sarpy.sicd_elements.SCPCOAType
        RadarCollection : sarpy.sicd_elements.RadarCollectionType
        ImageFormation : sarpy.sicd_elements.ImageFormationType

        Returns
        -------
        None
        """

        if RMA.RMAT is None:
            return

        if self.ImagePlane is None:
            self.ImagePlane = 'SLANT'
        if self.Type is None:
            self.Type = 'XCTYAT'

        if self.Row.UVectECF is None and self.Col.UVectECF is None:
            if SCPCOA is not None and SCPCOA.ARPPos is not None:
                SCP = SCPCOA.ARPPos.get_array()
                pos_ref = RMA.RMAT.PosRef.get_array()
                upos_ref = pos_ref / norm(pos_ref)
                vel_ref = RMA.RMAT.VelRef.get_array()
                uvel_ref = vel_ref / norm(vel_ref)
                uLOS = (SCP - pos_ref)  # it absolutely could be that SCP = pos_ref
                uLos_norm = norm(uLOS)
                if uLos_norm > 0:
                    uLOS /= uLos_norm
                    left = numpy.cross(upos_ref, uvel_ref)
                    look = numpy.sign(numpy.dot(left, uLOS))
                    uYAT = -look*uvel_ref
                    uSPZ = numpy.cross(uLOS, uYAT)
                    uSPZ /= norm(uSPZ)
                    uXCT = numpy.cross(uYAT, uSPZ)
                    self.Row.UVectECF = XYZType.from_array(uXCT)
                    self.Col.UVectECF = XYZType.from_array(uYAT)

        center_frequency = self._get_center_frequency(RadarCollection, ImageFormation)
        if center_frequency is not None and RMA.RMAT.DopConeAngRef is not None:
            if self.Row.KCtr is None:
                self.Row.KCtr = (2*center_frequency/speed_of_light)*numpy.sin(numpy.deg2rad(RMA.RMAT.DopConeAngRef))
            if self.Col.KCtr is None:
                self.Col.KCtr = (2*center_frequency/speed_of_light)*numpy.cos(numpy.deg2rad(RMA.RMAT.DopConeAngRef))

    def _derive_rma_rmcr(self, RMA, SCPCOA, RadarCollection, ImageFormation):
        """

        Parameters
        ----------
        RMA : sarpy.sicd_elements.RMAType
        SCPCOA : sarpy.sicd_elements.SCPCOAType
        RadarCollection : sarpy.sicd_elements.RadarCollectionType
        ImageFormation : sarpy.sicd_elements.ImageFormationType

        Returns
        -------
        None
        """

        if RMA.RMCR is None:
            return

        if self.ImagePlane is None:
            self.ImagePlane = 'SLANT'
        if self.Type is None:
            self.Type = 'XRGYCR'

        if self.Row.UVectECF is None and self.Col.UVectECF is None:
            if SCPCOA is not None and SCPCOA.ARPPos is not None:
                SCP = SCPCOA.ARPPos.get_array()
                pos_ref = RMA.RMAT.PosRef.get_array()
                upos_ref = pos_ref / norm(pos_ref)
                vel_ref = RMA.RMAT.VelRef.get_array()
                uvel_ref = vel_ref / norm(vel_ref)
                uLOS = (SCP - pos_ref)  # it absolutely could be that SCP = pos_ref
                uLos_norm = norm(uLOS)
                if uLos_norm > 0:
                    uLOS /= uLos_norm
                    left = numpy.cross(upos_ref, uvel_ref)
                    look = numpy.sign(numpy.dot(left, uLOS))
                    uXRG = uLOS
                    uSPZ = look*numpy.cross(uvel_ref, uXRG)
                    uSPZ /= norm(uSPZ)
                    uYCR = numpy.cross(uSPZ, uXRG)
                    self.Row.UVectECF = XYZType.from_array(uXRG)
                    self.Col.UVectECF = XYZType.from_array(uYCR)

        center_frequency = self._get_center_frequency(RadarCollection, ImageFormation)
        if center_frequency is not None:
            if self.Row.KCtr is None:
                self.Row.KCtr = 2*center_frequency/speed_of_light
            if self.Col.KCtr is None:
                self.Col.KCtr = 2*center_frequency/speed_of_light

    def _derive_rma_inca(self, RMA, SCPCOA, Position):
        """

        Parameters
        ----------
        RMA : sarpy.sicd_elements.RMAType
        SCPCOA : sarpy.sicd_elements.SCPCOAType
        Position : sarpy.sicd_elements.PositionType

        Returns
        -------
        None
        """

        if RMA.INCA is None:
            return

        if self.Type is None:
            self.Type = 'RGZERO'

        if RMA.INCA.TimeCAPoly is not None and Position is not None and Position.ARPPoly is not None and \
                self.Row.UVectECF is None and self.Col.UVectECF is None and SCPCOA is not None and \
                SCPCOA.ARPPos is not None:
            t_zero = RMA.INCA.TimeCAPoly.Coefs[0]
            ca_pos = Position.ARPPoly(t_zero)
            ca_vel = Position.ARPPoly.derivative_eval(t_zero)
            uca_pos = ca_pos/norm(ca_pos)
            uca_vel = ca_vel/norm(ca_vel)
            SCP = SCPCOA.ARPPos.get_array()
            uRg = (SCP - ca_pos)
            uRg_norm = norm(uRg)
            if uRg_norm > 0:
                uRg /= uRg_norm
                left = numpy.cross(uca_pos, uca_vel)
                look = numpy.sign(numpy.dot(left, uRg))
                uSPZ = -look*numpy.cross(uRg, uca_vel)
                uSPZ /= norm(uSPZ)
                uAZ = numpy.cross(uSPZ, uRg)
                self.Row.UVectECF = XYZType.from_array(uRg)
                self.Col.UVectECF = XYZType.from_array(uAZ)

        if self.Row is not None and self.Row.KCtr is None and RMA.INCA.FreqZero is not None:
            self.Row.KCtr = 2*RMA.INCA.FreqZero/speed_of_light
        if self.Col is not None and self.Col.KCtr is None:
            self.Col.KCtr = 0