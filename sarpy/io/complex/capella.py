# -*- coding: utf-8 -*-
"""
Functionality for reading Capella SAR data into a SICD model.
"""

import logging
import json
from typing import Dict, Any
from datetime import datetime
from scipy.constants import speed_of_light

import numpy

from ..general.base import BaseReader
from ..general.tiff import TiffDetails, NativeTiffChipper
from ..general.utils import parse_timestring, get_seconds, string_types
from .utils import fit_position_xvalidation
from .sicd_elements.blocks import XYZPolyType
from .sicd_elements.SICD import SICDType
from .sicd_elements.CollectionInfo import CollectionInfoType, RadarModeType
from .sicd_elements.ImageCreation import ImageCreationType
from .sicd_elements.ImageData import ImageDataType
from .sicd_elements.GeoData import GeoDataType, SCPType
from .sicd_elements.Position import PositionType
from .sicd_elements.Grid import GridType, DirParamType, WgtTypeType
from .sicd_elements.RadarCollection import RadarCollectionType, \
    WaveformParametersType, TxFrequencyType, ChanParametersType
from .sicd_elements.Timeline import TimelineType, IPPSetType
from .sicd_elements.ImageFormation import ImageFormationType, RcvChanProcType, \
    TxFrequencyProcType, ProcessingType


__classification__ = "UNCLASSIFIED"
__author__ = ("Thomas McCullough", "Wade Schwartzkopf")


########
# base expected functionality for a module with an implemented Reader


def is_a(file_name):
    """
    Tests whether a given file_name corresponds to a Capella SAR file.
    Returns a reader instance, if so.

    Parameters
    ----------
    file_name : str
        the file_name to check

    Returns
    -------
    CapellaReader|None
        `CapellaReader` instance if Capella file, `None` otherwise
    """


    try:
        csk_details = CapellaDetails(file_name)
        print('File {} is determined to be a Capella file.'.format(file_name))
        return CapellaReader(csk_details)
    except IOError:
        return None


###########
# parser and interpreter for tiff attributes

class CapellaDetails(object):
    """
    Parses and converts the Cosmo Skymed metadata
    """

    __slots__ = ('_tiff_details', '_img_desc_tags')

    def __init__(self, file_name):
        """

        Parameters
        ----------
        file_name : str
        """

        # verify that the file is a tiff file
        self._tiff_details = TiffDetails(file_name)
        # verify that ImageDescription tiff tag exists
        if 'ImageDescription' not in self._tiff_details.tags:
            raise IOError('No "ImageDescription" tag in the tiff.')

        img_format = self._tiff_details.tags['ImageDescription']
        # verify that ImageDescription has a reasonable format
        try:
            self._img_desc_tags = json.loads(img_format)  # type: Dict[str, Any]
        except Exception as e:
            logging.error('Failed deserializing the ImageDescription tag as json with error {}'.format(e))
            raise e
        # verify the file is not compressed
        self._tiff_details.check_compression()
        # verify the file is not tiled
        self._tiff_details.check_tiled()

    @property
    def file_name(self):
        """
        str: the file name
        """

        return self._tiff_details.file_name

    @property
    def tiff_details(self):
        # type: () -> TiffDetails
        """
        TiffDetails: The tiff details object.
        """

        return self._tiff_details

    def get_symmetry(self):
        """
        Gets the symmetry definition.

        Returns
        -------
        Tuple[bool, bool, bool]
        """

        return False, False, False

    def get_sicd(self):
        """
        Get the SICD metadata for the image.

        Returns
        -------
        SICDType
        """

        def extract_state_vector():
            # type: () -> (numpy.ndarray, numpy.ndarray, numpy.ndarray)
            vecs = collect['state']['state_vectors']
            times = numpy.zeros((len(vecs), ), dtype=numpy.float64)
            positions = numpy.zeros((len(vecs), 3), dtype=numpy.float64)
            velocities = numpy.zeros((len(vecs), 3), dtype=numpy.float64)
            for i, entry in enumerate(vecs):
                times[i] = get_seconds(parse_timestring(entry['time'], precision='ns'), start_time, precision='ns')
                positions[i, :] = entry['position']
                velocities[i, :] = entry['velocity']
            return times, positions, velocities

        def get_collection_info():
            # type: () -> CollectionInfoType
            coll_name = collect['platform']
            start_dt = start_time.astype('datetime64[us]').astype(datetime)
            mode = collect['mode'].strip().lower()
            if mode == 'stripmap':
                radar_mode = RadarModeType(ModeType='STRIPMAP')
            elif mode == 'sliding_spotlight':
                radar_mode = RadarModeType(ModeType='DYNAMIC STRIPMAP')
            else:
                raise ValueError('Got unhandled radar mode {}'.format(mode))

            return CollectionInfoType(
                CollectorName=coll_name,
                CoreName='{}{}{}'.format(start_dt.strftime('%d%b%y').upper(),
                                         coll_name,
                                         start_dt.strftime('%H%M%S')),
                RadarMode=radar_mode,
                Classification='UNCLASSIFIED',
                CollectType='MONOSTATIC')

        def get_image_creation():
            # type: () -> ImageCreationType
            from sarpy.__about__ import __version__
            return ImageCreationType(
                Application=self._tiff_details.tags['Software'],
                DateTime=parse_timestring(self._img_desc_tags['processing_time'], precision='us'),
                Profile='sarpy {}'.format(__version__),
                Site='Unknown')

        def get_image_data():
            # type: () -> ImageDataType
            img = collect['image']
            rows = img['columns']  # capella uses flipped row/column definition?
            cols = img['rows']
            if img['data_type'] == 'CInt16':
                pixel_type = 'RE16I_IM16I'
            else:
                raise ValueError('Got unhandled data_type {}'.format(img['data_type']))

            return ImageDataType(
                NumRows=rows, NumCols=cols,
                FirstRow=0, FirstCol=0,
                PixelType=pixel_type,
                FullImage=(rows, cols),
                SCPPixel=(0.5*rows, 0.5*cols))  # TODO: From Wade - verify SCPPixel definition

        def get_geo_data():
            # type: () -> GeoDataType
            return GeoDataType(SCP=SCPType(ECF=collect['image']['center_pixel']['target_position']))

        def get_position():
            # type: () -> PositionType
            px, py, pz = fit_position_xvalidation(state_time, state_position, state_velocity, max_degree=6)
            return PositionType(ARPPoly=XYZPolyType(X=px, Y=py, Z=pz))

        def get_grid():
            # type: () -> GridType

            img = collect['image']

            image_plane = 'OTHER'
            grid_type = 'PLANE'
            if self._img_desc_tags['product_type'] == 'SLC' and img['algorithm'] != 'backprojection':
                image_plane = 'SLANT'
                grid_type = 'RGZERO'

            coa_time = parse_timestring(img['center_pixel']['center_time'], precision='ns')
            row_imp_rsp_bw = 2*bw/speed_of_light
            row = DirParamType(
                SS=img['pixel_spacing_column'],
                ImpRespBW=row_imp_rsp_bw,
                ImpRespWid=img['range_resolution'],
                KCtr=2*fc/speed_of_light,
                DeltaK1=-0.5*row_imp_rsp_bw,
                DeltaK2=0.5*row_imp_rsp_bw,
                DeltaKCOAPoly=[[0.0, ], ],
                WgtType=WgtTypeType(
                    WindowName=img['range_window']['name'],
                    Parameters=img['range_window']['parameters']))

            col = DirParamType(
                SS=img['pixel_spacing_row'],
                ImpRespWid=img['azimuth_resolution'],
                KCtr=0,
                WgtType=WgtTypeType(
                    WindowName=img['azimuth_window']['name'],
                    Parameters=img['azimuth_window']['parameters']))
            # TODO: from Wade -
            #   1.) no way to find zero doppler spacing
            #   2.) no way to find Col.ImpRespBW
            #   3.) account for numeric WgtFunct

            return GridType(
                ImagePlane=image_plane,
                Type=grid_type,
                TimeCOAPoly=[[get_seconds(coa_time, start_time)], ],  # TODO: constant?
                Row=row,
                Col=col)

        def get_radar_colection():
            # type: () -> RadarCollectionType

            radar = collect['radar']
            freq_min = fc - 0.5*bw
            return RadarCollectionType(
                TxPolarization=radar['transmit_polarization'],
                TxFrequency=TxFrequencyType(Min=freq_min, Max=freq_min + bw),
                Waveform=[WaveformParametersType(
                    TxRFBandwidth=bw,
                    TxPulseLength=radar['pulse_duration'],
                    RcvDemodType='CHIRP',
                    ADCSampleRate=radar['sampling_frequency'],
                    TxFreqStart=freq_min)],
                RcvChannels=[ChanParametersType(
                    TxRcvPolarization='{}:{}'.format(radar['transmit_polarization'],
                                                     radar['receive_polarization']))])

        def get_timeline():
            # type: () -> TimelineType
            prf = collect['radar']['prf'][0]['prf']
            return TimelineType(
                CollectStart=start_time,
                CollectDuration=duration,
                IPP=[
                    IPPSetType(
                        TStart=0,
                        TEnd=duration,
                        IPPStart=0,
                        IPPEnd=duration*prf,
                        IPPPoly=(0, prf)), ])

        def get_image_formation():
            # type: () -> ImageFormationType

            algo = collect['image']['algorithm'].upper()
            processings = None
            if algo == 'BACKPROJECTION':
                processings = [ProcessingType(Type='Backprojected to DEM', Applied=True), ]
            if algo not in ('PFA', 'RMA', 'RGAZCOMP'):
                logging.warning(
                    'Image formation algorithm {} not one of the recognized SICD options, '
                    'being set to "OTHER".'.format(algo))
                algo = 'OTHER'

            return ImageFormationType(
                RcvChanProc=RcvChanProcType(NumChanProc=1, PRFScaleFactor=1),
                ImageFormAlgo=algo,
                TStartProc=0,
                TEndProc=duration,
                TxFrequencyProc=TxFrequencyProcType(
                    MinProc=radar_collection.TxFrequency.Min,
                    MaxProc=radar_collection.TxFrequency.Max),
                STBeamComp='NO',
                ImageBeamComp='NO',
                AzAutofocus='NO',
                RgAutofocus='NO',
                Processings=processings)

        # TODO: From Wade - Radiometric is not suitable?

        # extract general use information
        collect = self._img_desc_tags['collect']
        start_time = parse_timestring(collect['start_timestamp'], precision='ns')
        end_time = parse_timestring(collect['stop_timestamp'], precision='ns')
        duration = get_seconds(end_time, start_time, precision='ns')
        state_time, state_position, state_velocity = extract_state_vector()
        bw = collect['radar']['pulse_bandwidth']
        fc = collect['radar']['center_frequency']

        # define the sicd elements
        collection_info = get_collection_info()
        image_creation = get_image_creation()
        image_data = get_image_data()
        geo_data = get_geo_data()
        position = get_position()
        grid = get_grid()
        radar_collection = get_radar_colection()
        timeline = get_timeline()
        image_formation = get_image_formation()

        sicd = SICDType(
            CollectionInfo=collection_info,
            ImageCreation=image_creation,
            ImageData=image_data,
            GeoData=geo_data,
            Position=position,
            Grid=grid,
            RadarCollection=radar_collection,
            Timeline=timeline,
            ImageFormation=image_formation)
        sicd.derive()

        # NB: this does not currently have enough information to successfully execute
        # sicd.populate_rniirs(override=False)
        return sicd


class CapellaReader(BaseReader):
    """
    The Capella reader object.
    """

    __slots__ = ('_capella_details', )

    def __init__(self, capella_details):
        """

        Parameters
        ----------
        capella_details : str|CapellaDetails
        """

        if isinstance(capella_details, string_types):
            capella_details = CapellaDetails(capella_details)

        if not isinstance(capella_details, CapellaDetails):
            raise TypeError('The input argument for capella_details must be a '
                            'filename or CapellaDetails object')
        self._capella_details = capella_details
        sicd = self.capella_details.get_sicd()
        chipper = NativeTiffChipper(self.capella_details.tiff_details, symmetry=self.capella_details.get_symmetry())
        super(CapellaReader, self).__init__(sicd, chipper, is_sicd_type=True)

    @property
    def capella_details(self):
        # type: () -> CapellaDetails
        """
        CapellaDetails: The capella details object.
        """

        return self._capella_details

    @property
    def file_name(self):
        return self.capella_details.file_name
