# -*- coding: utf-8 -*-
"""
A base calculator class for Fourier processing schemes.
"""

__classification__ = "UNCLASSIFIED"
__author__ = 'Thomas McCullough'

import logging
from typing import Union, Tuple, List, Any

from sarpy.compliance import string_types, integer_types, int_func
from sarpy.io.complex.converter import open_complex
from sarpy.io.general.base import BaseReader
from sarpy.io.general.slice_parsing import validate_slice_int, validate_slice
from sarpy.io.complex.sicd_elements.SICD import SICDType

# NB: the below are intended as common imports from other locations - leave them here
import numpy
import scipy
if scipy.__version__ < '1.4':
    from scipy.fftpack import fft, ifft, fftshift
else:
    from scipy.fft import fft, ifft, fftshift


class FFTCalculator(object):
    """
    Base class for Fourier processing calculator class.

    This is intended for processing schemes where full resolution is required along
    the processing dimension, so sub-sampling along the processing dimension does
    not decrease the amount of data which must be fetched.
    """

    __slots__ = (
        '_reader', '_index', '_sicd', '_platform_direction', '_dimension', '_data_size',
        '_fill', '_block_size')


    def __init__(self, reader, dimension=0, index=0, block_size=50):
        """

        Parameters
        ----------
        reader : str|BaseReader
            Input file path or reader object, which must be of sicd type.
        dimension : int
            The dimension over which to split the sub-aperture.
        index : int
            The sicd index to use.
        block_size : int
            The approximate processing block size to fetch, given in MB. The
            minimum value for use here will be 1.
        """

        self._index = None # set explicitly
        self._sicd = None  # set with index setter
        self._platform_direction = None  # set with the index setter
        self._dimension = None # set explicitly
        self._data_size = None  # set with index setter
        self._fill = None # set implicitly with _set_fill()
        self._block_size = None # set explicitly

        # validate the reader
        if isinstance(reader, string_types):
            reader = open_complex(reader)
        if not isinstance(reader, BaseReader):
            raise TypeError('reader is required to be a path name for a sicd-type image, '
                            'or an instance of a reader object.')
        if not reader.is_sicd_type:
            raise TypeError('reader is required to be of sicd_type.')
        self._reader = reader
        # set the other properties
        self.dimension = dimension
        self.index = index
        self.block_size = block_size

    @property
    def reader(self):
        # type: () -> BaseReader
        """
        BaseReader: The reader instance.
        """

        return self._reader

    @property
    def dimension(self):
        # type: () -> int
        """
        int: The dimension along which to perform the color subaperture split.
        """

        return self._dimension

    @dimension.setter
    def dimension(self, value):
        value = int_func(value)
        if value not in [0, 1]:
            raise ValueError('dimension must be 0 or 1, got {}'.format(value))
        self._dimension = value
        self._set_fill()

    @property
    def data_size(self):
        # type: () -> Tuple[int, int]
        """
        Tuple[int, int]: The data size for the reader at the given index.
        """

        return self._data_size

    @property
    def index(self):
        # type: () -> int
        """
        int: The index of the reader.
        """

        return self._index

    @index.setter
    def index(self, value):
        value = int_func(value)
        if value < 0:
            raise ValueError('The index must be a non-negative integer, got {}'.format(value))

        sicds = self.reader.get_sicds_as_tuple()
        if value >= len(sicds):
            raise ValueError('The index must be less than the sicd count.')
        self._index = value
        self._sicd = sicds[value]

        if self._sicd.SCPCOA is None or self._sicd.SCPCOA.SideOfTrack is None:
            logging.warning(
                'The sicd object at index {} has unpopulated SCPCOA.SideOfTrack. '
                'Defaulting to "R", which may be incorrect.')
            self._platform_direction = 'R'
        else:
            self._platform_direction = self._sicd.SCPCOA.SideOfTrack

        self._data_size = self.reader.get_data_size_as_tuple()[value]
        self._set_fill()

    @property
    def fill(self):
        # type: () -> float
        """
        float: The fill factor for the fourier processing.
        """

        return self._fill

    def _set_fill(self):
        self._fill = None
        if self._dimension is None:
            return
        if self._index is None:
            return

        if self.dimension == 0:
            try:
                fill = 1.0/(self.sicd.Grid.Row.SS*self.sicd.Grid.Row.ImpRespBW)
            except (ValueError, AttributeError, TypeError):
                fill = 1.0
        else:
            try:
                fill = 1.0/(self.sicd.Grid.Col.SS*self.sicd.Grid.Col.ImpRespBW)
            except (ValueError, AttributeError, TypeError):
                fill = 1.0
        self._fill = max(1.0, float(fill))

    @property
    def block_size(self):
        # type: () -> int
        """
        int: The approximate processing block size in MB.
        """

        return self._block_size

    @block_size.setter
    def block_size(self, value):
        if value is None:
            value = 50
        value = int_func(value)
        if value < 1:
            value = 1
        self._block_size = value

    @property
    def block_size_in_bytes(self):
        # type: () -> int
        """
        int: The approximate processing block size in bytes.
        """

        return self._block_size*(2**20)

    @property
    def sicd(self):
        # type: () -> SICDType
        """
        SICDType: The sicd structure.
        """

        return self._sicd

    def _parse_slicing(self, item):
        # type: (Union[None, int, slice, tuple]) -> Tuple[Tuple[int, int, int], Tuple[int, int, int], Any]

        def parse(entry, dimension):
            bound = self.data_size[dimension]
            if entry is None:
                return 0, bound, 1
            elif isinstance(entry, integer_types):
                entry = validate_slice_int(entry, bound)
                return entry, entry+1, 1
            elif isinstance(entry, slice):
                entry = validate_slice(entry, bound)
                return entry.start, entry.stop, entry.step
            else:
                raise TypeError('No support for slicing using type {}'.format(type(entry)))

        # this input is assumed to come from slice parsing
        if isinstance(item, tuple):
            if len(item) > 3:
                raise ValueError(
                    'CSICalculator received slice argument {}. We cannot slice '
                    'on more than two dimensions.'.format(item))
            elif len(item) == 3:
                return parse(item[0], 0), parse(item[1], 1), item[3]
            elif len(item) == 2:
                return parse(item[0], 0), parse(item[1], 1), None
            elif len(item) == 1:
                return parse(item[0], 0), parse(None, 1), None
            else:
                return parse(None, 0), parse(None, 1), None
        elif isinstance(item, slice):
            return parse(item, 0), parse(None, 1), None
        elif isinstance(item, integer_types):
            return parse(item, 0), parse(None, 1), None
        else:
            raise TypeError('CSICalculator does not support slicing using type {}'.format(type(item)))

    def get_fetch_block_size(self, start_element, stop_element):
        """
        Gets the fetch block size for the given full resolution section.
        This assumes that the fetched data will be 8 bytes per pixel, in
        accordance with single band complex64 data.

        Parameters
        ----------
        start_element : int
        stop_element : int

        Returns
        -------
        int
        """

        if stop_element == start_element:
            return None

        full_size = float(abs(stop_element - start_element))
        return max(1, int_func(numpy.ceil(self.block_size_in_bytes/float(8*full_size))))

    @staticmethod
    def extract_blocks(the_range, block_size):
        # type: (Tuple[int, int, int], int) -> (List[Tuple[int, int, int]], List[Tuple[int, int]])
        """
        Convert the single range definition into a series of range defintions in
        keeping with fetching of the appropriate block sizes.

        Parameters
        ----------
        the_range : Tuple[int, int, int]
            The input (off processing axis) range.
        block_size : None|int|float
            The size of blocks (number of indices).

        Returns
        -------
        List[Tuple[int, int, int]], List[Tuple[int, int]]
            The sequence of range definitions `(start index, stop index, step)`
            relative to the overall image, and the sequence of start/stop indices
            for positioning of the given range relative to the original range.
        """

        entries = numpy.arange(the_range[0], the_range[1], the_range[2], dtype=numpy.int64)
        if block_size is None:
            return [the_range, ], [(0, entries.size), ]

        # how many blocks?
        block_count = int_func(numpy.ceil(entries.size/float(block_size)))
        if block_size == 1:
            return [the_range, ], [(0, entries.size), ]

        # workspace for what the blocks are
        out1 = []
        out2 = []
        start_ind = 0
        for i in range(block_count):
            end_ind = start_ind+block_size
            if end_ind < entries.size:
                block1 = (int_func(entries[start_ind]), int_func(entries[end_ind]), the_range[2])
                block2 = (start_ind, end_ind)
            else:
                block1 = (int_func(entries[start_ind]), the_range[1], the_range[2])
                block2 = (start_ind, entries.size)
            out1.append(block1)
            out2.append(block2)
            start_ind = end_ind
        return out1, out2

    def get_data_mean_magnitude(self, bounds):
        """
        Gets the mean magnitude in the region defined by bounds.

        Parameters
        ----------
        bounds : numpy.ndarray
            Of the form `(row_start, row_end, col_start, col_end)`.

        Returns
        -------
        float
        """

        # Extract the mean of the data magnitude - for global remap usage
        mean_block_size = self.get_fetch_block_size(bounds[0], bounds[1])
        mean_column_blocks, _ = self.extract_blocks(
            (bounds[2], bounds[3], 1), block_size=mean_block_size)
        mean_total = 0.0
        mean_count = 0
        for this_column_range in mean_column_blocks:
            data = numpy.abs(self.reader[
                             bounds[0]:bounds[1],
                             this_column_range[0]:this_column_range[1],
                             self.index])
            mean_total += numpy.sum(data)
            mean_count += data.size
        return float(mean_total / mean_count)

    def __getitem__(self, item):
        """
        Fetches the processed data based on the input slice.

        Parameters
        ----------
        item

        Returns
        -------
        numpy.ndarray
        """

        raise NotImplementedError


def _validate_fft_input(array):
    """
    Validate the fft input.

    Parameters
    ----------
    array : numpy.ndarray

    Returns
    -------
    None
    """

    if not isinstance(array, numpy.ndarray):
        raise TypeError('array must be a numpy array')
    if not numpy.iscomplexobj(array):
        raise ValueError('array must have a complex data type')
    if array.ndim != 2:
        raise ValueError('array must be a two-dimensional array. Got shape {}'.format(array.shape))


def _determine_direction(sicd, dimension):
    """
    Determine the default sign for the fft.

    Parameters
    ----------
    sicd : SICDType
    dimension : int

    Returns
    -------
    int
    """

    sgn = None
    if dimension == 0:
        try:
            sgn = sicd.Grid.Row.Sgn
        except AttributeError:
            pass
    elif dimension == 1:
        try:
            sgn = sicd.Grid.Col.Sgn
        except AttributeError:
            pass
    else:
        raise ValueError('dimension must be one of 0 or 1.')
    return 1 if sgn is None else sgn


def fft_sicd(array, dimension, sicd):
    """
    Apply the forward one-dimensional forward fft to data associated with the given sicd
    along the given dimension/axis.

    Parameters
    ----------
    array : numpy.ndarray
        The data array, which must be two-dimensional and complex.
    dimension : int
        Must be one of 0, 1.
    sicd : SICDType
        The associated SICD structure.

    Returns
    -------
    numpy.ndarray
    """

    sgn = _determine_direction(sicd, dimension)
    return fft(array, axis=dimension) if sgn > 0 else ifft(array, axis=dimension)


def ifft_sicd(array, dimension, sicd):
    """
    Apply the inverse one-dimensional fft to data associated with the given sicd
    along the given dimension/axis.

    Parameters
    ----------
    array : numpy.ndarray
        The data array, which must be two-dimensional and complex.
    dimension : int
        Must be one of 0, 1.
    sicd : SICDType
        The associated SICD structure.

    Returns
    -------
    numpy.ndarray
    """

    sgn = _determine_direction(sicd, dimension)
    return ifft(array, axis=dimension) if sgn > 0 else fft(array, axis=dimension)


def fft2_sicd(array, sicd):
    """
    Apply the forward two-dimensional fft (i.e. both axes) to data associated with
    the given sicd.

    Parameters
    ----------
    array : numpy.ndarray
        The data array, which must be two-dimensional and complex.
    sicd : SICDType
        The associated SICD structure.

    Returns
    -------
    numpy.ndarray
    """

    return fft_sicd(fft_sicd(array, 0, sicd), 1, sicd)


def ifft2_sicd(array, sicd):
    """
    Apply the inverse two-dimensional fft (i.e. both axes) to data associated with
    the given sicd.

    Parameters
    ----------
    array : numpy.ndarray
        The data array, which must be two-dimensional and complex.
    sicd : SICDType
        The associated SICD structure.

    Returns
    -------
    numpy.ndarray
    """

    return ifft_sicd(ifft_sicd(array, 0, sicd), 1, sicd)