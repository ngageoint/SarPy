# -*- coding: utf-8 -*-
"""
Functionality for dealing with NITF file header information. This is specifically
geared towards SICD file usage, and some functionality may not allow full generality.
See MIL-STD-2500C for specification details.
"""

import logging
import sys
from collections import OrderedDict
from typing import Union, Tuple
import struct

import numpy

integer_types = (int, )
string_types = (str, )
int_func = int
if sys.version_info[0] < 3:
    # noinspection PyUnresolvedReferences
    int_func = long  # to accommodate for 32-bit python 2
    # noinspection PyUnresolvedReferences
    integer_types = (int, long)
    # noinspection PyUnresolvedReferences
    string_types = (str, unicode)

__classification__ = "UNCLASSIFIED"
__author__ = "Thomas McCullough"


#####
# Basic Components

class _BaseScraper(object):
    """Describes the abstract functionality"""
    __slots__ = ()

    def __len__(self):
        raise NotImplementedError

    def __str__(self):
        # TODO: improve this behavior...
        def get_str(el):
            if isinstance(el, string_types):
                return '"{}"'.format(el.strip())
            else:
                return str(el)

        var_str = ','.join('{}={}'.format(el, get_str(getattr(self, el)).strip()) for el in self.__slots__)
        return '{}(\n\t{}\n)'.format(self.__class__.__name__, var_str)

    @classmethod
    def minimum_length(cls):
        """
        The minimum size it takes to write such a header.

        Returns
        -------
        int
        """

        raise NotImplementedError

    @classmethod
    def from_bytes(cls, value, start, **args):
        """

        Parameters
        ----------
        value: bytes|str
            the header string to scrape
        start : int
            the beginning location in the string
        args : dict
            keyword arguments

        Returns
        -------
        """

        raise NotImplementedError

    def to_bytes(self):
        """
        Write the object to a properly packed str.

        Returns
        -------
        bytes
        """

        raise NotImplementedError

    @classmethod
    def _validate(cls, value, start):
        if isinstance(value, string_types):
            value = value.encode()
        if not isinstance(value, bytes):
            raise TypeError('Requires a bytes or str type input, got {}'.format(type(value)))

        min_length = cls.minimum_length()
        if len(value) < start + min_length:
            raise TypeError('Requires a bytes or str type input of length at least {}, '
                            'got {}'.format(min_length, len(value[start:])))
        return value


class _ItemArrayHeaders(_BaseScraper):
    """
    Item array in the NITF header (i.e. Image Segment, Text Segment).
    This is not really meant to be used directly.
    """

    __slots__ = ('subhead_len', 'subhead_sizes', 'item_len', 'item_sizes')

    def __init__(self, subhead_len=0, subhead_sizes=None, item_len=0, item_sizes=None):
        """

        Parameters
        ----------
        subhead_len : int
        subhead_sizes : numpy.ndarray|None
        item_len : int
        item_sizes : numpy.ndarray|None
        """
        if subhead_sizes is None or item_sizes is None:
            subhead_sizes = numpy.zeros((0, ), dtype=numpy.int64)
            item_sizes = numpy.zeros((0,), dtype=numpy.int64)
        if subhead_sizes.shape != item_sizes.shape or len(item_sizes.shape) != 1:
            raise ValueError(
                'the subhead_offsets and item_offsets arrays must one-dimensional and the same length')
        self.subhead_len = subhead_len
        self.subhead_sizes = subhead_sizes
        self.item_len = item_len
        self.item_sizes = item_sizes

    def __len__(self):
        return 3 + (self.subhead_len + self.item_len)*self.subhead_sizes.size

    @classmethod
    def minimum_length(cls):
        return 3

    @classmethod
    def from_bytes(cls, value, start, subhead_len=0, item_len=0):
        """

        Parameters
        ----------
        value : bytes|str
        start : int
        subhead_len : int
        item_len : int

        Returns
        -------
        _ItemArrayHeaders
        """

        subhead_len, item_len = int_func(subhead_len), int_func(item_len)

        value = cls._validate(value, start)

        loc = start
        count = int_func(value[loc:loc+3])
        loc += 3
        subhead_sizes = numpy.zeros((count, ), dtype=numpy.int64)
        item_sizes = numpy.zeros((count, ), dtype=numpy.int64)
        for i in range(count):
            subhead_sizes[i] = int_func(value[loc: loc+subhead_len])
            loc += subhead_len
            item_sizes[i] = int_func(value[loc: loc+item_len])
            loc += item_len
        return cls(subhead_len, subhead_sizes, item_len, item_sizes)

    def to_bytes(self):
        out = '{0:03d}'.format(self.subhead_sizes.size)
        subh_frm = '{0:0' + str(self.subhead_len) + 'd}'
        item_frm = '{0:0' + str(self.item_len) + 'd}'
        for sh_off, it_off in zip(self.subhead_sizes, self.item_sizes):
            out += subh_frm.format(sh_off) + item_frm.format(it_off)
        return out.encode()


class OtherHeader(_BaseScraper):
    """
    User defined header section at the end of the NITF header
    (i.e. Image Segment, Text Segment). This is not really meant to be
    used directly.
    """

    __slots__ = ('overflow', 'header')

    def __init__(self, overflow=None, header=None):
        if overflow is None:
            self.overflow = 0
        else:
            self.overflow = int_func(overflow)
        if header is None:
            self.header = header
        elif not isinstance(header, string_types):
            raise ValueError('header must be of string type')
        elif len(header) > 99991:
            logging.warning('Other header will be truncated to 99,9991 characters from {}'.format(header))
            self.header = header[:99991]
            self.overflow += len(header) - 99991
        else:
            self.header = header

    def __len__(self):
        length = 5
        if self.header is not None:
            length += 3 + len(self.header)
        return length

    @classmethod
    def minimum_length(cls):
        return 5

    @classmethod
    def from_bytes(cls, value, start, **args):
        if value is None:
            return cls(**args)

        value = cls._validate(value, start)
        siz = int_func(value[start:start+5])
        if siz == 0:
            return cls()
        else:
            overflow = int_func(value[start+5:start+8])
            header = value[start+8:start+siz]
            return cls(overflow=overflow, header=header)

    def to_bytes(self):
        out = '{0:05d}'.format(self.overflow)
        if self.header is not None:
            if self.overflow > 999:
                out += '999'
            else:
                out += '{0:03d}'.format(self.overflow)
            out += self.header
        return out.encode()


class _HeaderScraper(_BaseScraper):
    """
    Generally abstract class for scraping NITF header components
    """

    __slots__ = ()  # the possible attribute collection
    _types = {}  # for elements which will be scraped by another class
    _args = {}  # for elements which will be scraped by another class, these are args for the from_bytes method
    _formats = {}  # {attribute: '<length>d/s'} for each entry in __slots__ not in types
    _defaults = {}  # any default values.
    # If a given attribute doesn't have a give default it is assumed that all spaces is the default

    def __init__(self, **kwargs):
        settable_attributes = self._get_settable_attributes()
        unmatched = [key for key in kwargs if key not in settable_attributes]
        if len(unmatched) > 0:
            raise KeyError('Arguments {} are not in the list of allowed '
                           'attributes {}'.format(unmatched, settable_attributes))
        # the things with no defaults
        no_defaults = [key for key in settable_attributes if
                       (key not in kwargs and not (key in self._defaults or '_'+key in self._types))]

        if len(no_defaults) > 0:
            logging.warning(
                'Attributes {} of class {} are not provided in the construction, '
                'but do not allow for suitable defaults.\nThey will be initialized, '
                'probably to a foolish or invalid value.\nBe sure to set them appropriately '
                'for a valid NITF header.'.format(no_defaults, self.__class__.__name__))

        for attribute in settable_attributes:
            setattr(self, attribute, kwargs.get(attribute, None))

    @classmethod
    def _get_settable_attributes(cls):  # type: () -> tuple
        # properties
        return tuple(map(lambda x: x[1:] if x[0] == '_' else x, cls.__slots__))

    @classmethod
    def _get_format_string(cls, attribute):
        if attribute not in cls._formats:
            return None
        fstr = cls._formats[attribute]
        leng = int_func(fstr[:-1])
        frmstr = '{0:0' + fstr + '}' if fstr[-1] == 'd' else '{0:' + fstr + '}'
        return leng, frmstr

    def __setattr__(self, attribute, value):
        # is this thing a property? If so, just pass it straight through to setter
        if isinstance(getattr(type(self), attribute, None), property):
            object.__setattr__(self, attribute, value)
            return

        if attribute in self._types:
            typ = self._types[attribute]
            if value is None:
                object.__setattr__(self, attribute, typ())
            elif isinstance(value, _BaseScraper):
                object.__setattr__(self, attribute, value)
            else:
                raise ValueError('Attribute {} is expected to be of type {}, '
                                 'got {}'.format(attribute, typ, type(value)))
        elif attribute in self._formats:
            frmt = self._formats[attribute]
            lng = int_func(frmt[:-1])
            if value is None:
                value = self._defaults.get(attribute, None)

            if frmt[-1] == 'd':  # an integer
                if value is None:
                    object.__setattr__(self, attribute, 0)
                else:
                    val = int_func(value)
                    if 0 <= val < int_func(10)**lng:
                        object.__setattr__(self, attribute, val)
                    else:
                        raise ValueError('Attribute {} is expected to be an integer expressible in {} digits. '
                                         'Got {}.'.format(attribute, lng, value))
            elif frmt[-1] == 's':  # a string
                frmtstr = '{0:' + frmt + '}'
                if value is None:
                    object.__setattr__(self, attribute, frmtstr.format('\x20'))  # spaces
                else:
                    if isinstance(value, bytes):
                        value = value.decode('utf-8')
                    if not isinstance(value, string_types):
                        raise TypeError('Attribute {} is expected to a string, got {}'.format(attribute, type(value)))

                    if len(value) > lng:
                        logging.warning('Attribute {} is expected to be a string of at most {} characters. '
                                        'Got a value of {} characters, '
                                        'so truncating'.format(attribute, lng, len(value)))
                        object.__setattr__(self, attribute, value[:lng])
                    else:
                        object.__setattr__(self, attribute, frmtstr.format(value))
            elif frmt[-1] == 'b':  # don't interpret
                lng = int(frmt[:-1])
                if value is None:
                    object.__setattr__(self, attribute, b'\x00'*lng)
                elif isinstance(value, bytes):
                    if len(value) != lng:
                        raise ValueError('Attribute {} must take a bytes of length {}'.format(attribute, lng))
                    object.__setattr__(self, attribute, value)
                elif isinstance(value, string_types):
                    if len(value) != lng:
                        raise ValueError('Attribute {} must take a bytes of length {}'.format(attribute, lng))
                    object.__setattr__(self, attribute, value.encode())
            else:
                raise ValueError('Unhandled format {}'.format(frmt))
        else:
            object.__setattr__(self, attribute, value)

    def __len__(self):
        length = 0
        for attribute in self.__slots__:
            if attribute in self._types:
                val = getattr(self, attribute)
                length += len(val)
            else:
                length += int_func(self._formats[attribute][:-1])
        return length

    @classmethod
    def minimum_length(cls):
        min_length = 0
        for attribute in cls.__slots__:
            if attribute in cls._types:
                typ = cls._types[attribute]
                if issubclass(typ, _BaseScraper):
                    min_length += typ.minimum_length()
            else:
                min_length += int_func(cls._formats[attribute][:-1])
        return min_length

    @classmethod
    def _parse_attributes(cls, value, start):
        fields = OrderedDict()
        loc = start
        for attribute in cls.__slots__:
            if attribute in cls._types:
                typ = cls._types[attribute]
                if not issubclass(typ, _BaseScraper):
                    raise TypeError('Invalid class definition, any entry of _types must extend _BaseScraper')
                args = cls._args.get(attribute, {})
                val = typ.from_bytes(value, loc, **args)
                aname = attribute[1:] if attribute[0] == '_' else attribute
                fields[aname] = val  # exclude the underscore from the name
                lngt = len(val)
            else:
                lngt = int_func(cls._formats[attribute][:-1])
                fields[attribute] = value[loc:loc + lngt]
            loc += lngt
        return fields, loc

    @classmethod
    def from_bytes(cls, value, start, **kwargs):
        if value is None:
            return cls(**kwargs)

        value = cls._validate(value, start)
        fields, _ = cls._parse_attributes(value, start)
        return cls(**fields)

    def to_bytes(self):
        out = b''
        for attribute in self.__slots__:
            val = getattr(self, attribute)
            if isinstance(val, _BaseScraper):
                out += val.to_bytes()
            elif isinstance(val, integer_types):
                _, fstr = self._get_format_string(attribute)
                out += fstr.format(val).encode()
            elif isinstance(val, string_types):
                # NB: length has already been controlled by the setter
                out += val.encode()
            elif isinstance(val, bytes):
                out += val
            else:
                raise TypeError('Got unhandled attribute value type {}'.format(type(val)))
        return out


#######
# Security tags - this is used in a variety of places

class NITFSecurityTags(_HeaderScraper):
    """
    The NITF security tags - described in SICD standard 2014-09-30, Volume II, page 20
    """

    __slots__ = (
        'CLAS', 'CLSY', 'CODE', 'CTLH',
        'REL', 'DCTP', 'DCDT', 'DCXM',
        'DG', 'DGDT', 'CLTX', 'CAPT',
        'CAUT', 'CRSN', 'SRDT', 'CTLN')
    _formats = {
        'CLAS': '1s', 'CLSY': '2s', 'CODE': '11s', 'CTLH': '2s',
        'REL': '20s', 'DCTP': '2s', 'DCDT': '8s', 'DCXM': '4s',
        'DG': '1s', 'DGDT': '8s', 'CLTX': '43s', 'CAPT': '1s',
        'CAUT': '40s', 'CRSN': '1s', 'SRDT': '8s', 'CTLN': '15s'}
    _defaults = {
        'CLAS': 'U', 'CLSY': '\x20', 'CODE': '\x20', 'CTLH': '\x20',
        'REL': '\x20', 'DCTP': '\x20', 'DCDT': '\x20', 'DCXM': '\x20',
        'DG': '\x20', 'DGDT': '\x20', 'CLTX': '\x20', 'CAPT': '\x20',
        'CAUT': '\x20', 'CRSN': '\x20', 'SRDT': '\x20', 'CTLN': '\x20'}


######
# Partially general image segment header

class ImageBand(_HeaderScraper):
    """
    Single image band, part of the image bands collection
    """
    __slots__ = ('IREPBAND', 'ISUBCAT', 'IFC', 'IMFLT', '_LUTD')
    _formats = {'IREPBAND': '2s', 'ISUBCAT': '6s', 'IFC': '1s', 'IMFLT': '3s'}
    _defaults = {'IREPBAND': '\x20', 'ISUBCAT': '\x20', 'IFC': 'N', 'IMFLT': '\x20'}

    def __init__(self, **kwargs):
        self._LUTD = None
        super(ImageBand, self).__init__(**kwargs)

    @property
    def LUTD(self):
        return self._LUTD

    @LUTD.setter
    def LUTD(self, value):
        if value is None:
            self._LUTD = None
            return

        if not isinstance(value, numpy.ndarray):
            raise TypeError('LUTD must be a numpy array')
        if value.dtype.name != 'uint8':
            raise ValueError('LUTD must be a numpy array of dtype uint8, got {}'.format(value.dtype.name))
        if value.ndim != 2:
            raise ValueError('LUTD must be a two-dimensional array')
        if value.shape[0] > 4:
            raise ValueError(
                'The number of LUTD bands (axis 0) must be 4 or fewer. '
                'Got LUTD shape {}'.format(value.shape))
        if value.shape[1] > 65536:
            raise ValueError(
                'The number of LUTD elemnts (axis 1) must be 65536 or fewer. '
                'Got LUTD shape {}'.format(value.shape))
        self._LUTD = value

    @property
    def NLUTS(self):
        return 0 if self._LUTD is None else self._LUTD.shape[0]

    @property
    def NELUTS(self):
        return 0 if self._LUTD is None else self._LUTD.shape[1]

    def __len__(self):
        nluts = self.NLUTS
        if nluts == 0:
            return 13
        else:
            neluts = self.NELUT
            return 18 + nluts*neluts

    @classmethod
    def minimum_length(cls):
        return 13

    @classmethod
    def from_bytes(cls, value, start, **kwargs):
        if value is None:
            return cls(**kwargs)

        value = cls._validate(value, start)
        loc = start
        fields = {
            'IREPBAND': value[loc:loc+2].decode('utf-8'),
            'ISUBCAT': value[loc+2:loc+8].decode('utf-8'),
            'IFC': value[loc+8:loc+9].decode('utf-8'),
            'IMFLT': value[loc+9:loc+12].decode('utf-8'),
        }
        nluts = int_func(value[loc + 12:loc + 13])
        if nluts == 0:
            fields['LUTD'] = None
        else:
            neluts = int_func(value[loc + 13:loc + 18])
            lutd = numpy.array(
                struct.unpack('{}B'.format(nluts*neluts)), dtype=numpy.uint8).reshape((nluts, neluts))
            fields['LUTD'] = lutd
        return cls(**fields)

    def to_bytes(self):
        out = b''
        for attribute in ('IREPBAND', 'ISUBCAT', 'IFC', 'IMFLT'):
            out += getattr(self, attribute).encode()
        if self.NLUTS == 0:
            return out + b'0'
        out += '{0:d}{1:05d}'.format(self.NLUTS, self.NELUTS).encode()
        out += struct.pack('{}B'.format(self.NLUTS*self.NELUTS, *self.LUTD.flatten()))
        return out


class ImageBands(_BaseScraper):
    """
    Image bands in the image sub-header.
    """
    __slots__ = ('_BANDS', )

    def __init__(self, bands):
        if not isinstance(bands, (list, tuple)):
            raise ValueError('bands must be a list or tuple, got {}'.format(type(bands)))
        if len(bands) == 0:
            raise ValueError('bands must have length > 0.')
        for i, entry in enumerate(bands):
            if not isinstance(entry, ImageBand):
                raise TypeError('All entries of bands must be an instance of ImageBand, '
                                'got {} for entry {}'.format(type(entry), i))
        self._BANDS = tuple(bands)

    @property
    def BANDS(self):  # type: () -> Tuple[ImageBand, ...]
        return self._BANDS

    def __len__(self):
        length = 1
        if len(self.BANDS) > 9:
            length += 5
        return length + sum(len(entry) for entry in self._BANDS)

    @classmethod
    def minimum_length(cls):
        return 14

    @classmethod
    def from_bytes(cls, value, start, **kwargs):
        value = cls._validate(value, start)
        loc = start
        count = int_func(value[loc:loc+1])  # check nbands (9 or fewer)
        loc += 1
        if count == 0:
            # (only) if there are more than 9, a longer field is used
            count = int_func(value[loc:loc+5])
            loc += 5
        bands = []
        for i in range(count):
            band = ImageBand.from_bytes(value, loc)
            bands.append(band)
            loc += len(band)
        return cls(bands)

    def to_bytes(self):
        siz = len(self.BANDS)
        if siz <= 9:
            items = ['{0:1d}'.format(siz).encode(), ]
        else:
            items = ['0{0:05d}'.format(siz).encode(), ]
        for band in self.BANDS:
            items.append(band.to_bytes())
        return b''.join(items)


class ImageComments(_BaseScraper):
    """
    Image comments in the image subheader
    """

    __slots__ = ('comments', )

    def __init__(self, comments=None):
        if comments is None:
            self.comments = []
        elif isinstance(comments, string_types):
            self.comments = [comments, ]
        else:
            comments = list(comments)
            self.comments = comments

        if len(self.comments) > 9:
            logging.warning('Only the first 9 comments will be used, got a list of '
                            'length {}'.format(len(self.comments)))

    def __len__(self):
        return 1 + 80*min(len(self.comments), 9)

    @classmethod
    def minimum_length(cls):
        return 1

    @classmethod
    def from_bytes(cls, value, start, **args):
        value = cls._validate(value, start)
        loc = start
        count = int_func(value[loc:loc+1])
        loc += 1
        comments = []
        for i in range(count):
            comments.append(value[loc: loc+80])
            loc += 80
        return cls(comments)

    def to_bytes(self):
        if self.comments is None or len(self.comments) == 0:
            return b'0'

        siz = min(len(self.comments), 9)
        out = '{0:1d}'.format(siz)
        for i in range(siz):
            val = self.comments[i]
            if len(val) < 80:
                out += '{0:80s}'.format(val)
            else:
                out += val[:80]
        return out.encode()


class ImageSegmentHeader(_HeaderScraper):
    """
    The Image Segment header - described in SICD standard 2014-09-30, Volume II, page 24
    """

    # TODO: this is not general, and is really tailored to a sicd
    #  LOW - if IC != "NC", we need to have a COMRAT field
    #  LOW - accommodate UDIDL > 0
    #  LOW - accommodate IXSHDL > 0

    __slots__ = (
        'IM', 'IID1', 'IDATIM', 'TGTID',
        'IID2', '_Security', 'ENCRYP', 'ISORCE',
        'NROWS', 'NCOLS', 'PVTYPE', 'IREP',
        'ICAT', 'ABPP', 'PJUST', 'ICORDS',
        'IGEOLO', '_ImageComments', 'IC', '_ImageBands',
        'ISYNC', 'IMODE', 'NBPR', 'NBPC', 'NPPBH',
        'NPPBV', 'NBPP', 'IDLVL', 'IALVL',
        'ILOC', 'IMAG', 'UDIDL', 'IXSHDL')
    _formats = {
        'IM': '2s', 'IID1': '10s', 'IDATIM': '14s', 'TGTID': '17s',
        'IID2': '80s', 'ENCRYP': '1s', 'ISORCE': '42s',
        'NROWS': '8d', 'NCOLS': '8d', 'PVTYPE': '3s', 'IREP': '8s',
        'ICAT': '8s', 'ABPP': '2d', 'PJUST': '1s', 'ICORDS': '1s',
        'IGEOLO': '60s', 'IC': '2s', 'ISYNC': '1d', 'IMODE': '1s',
        'NBPR': '4d', 'NBPC': '4d', 'NPPBH': '4d', 'NPPBV': '4d',
        'NBPP': '2d', 'IDLVL': '3d', 'IALVL': '3d', 'ILOC': '10s',
        'IMAG': '4s', 'UDIDL': '5d', 'IXSHDL': '5d'}
    _defaults = {
        'IM': 'IM', 'TGTID': '\x20', 'ENCRYP': '0',
        'IREP': 'NODISPLY', 'ICAT': 'SAR', 'PJUST': 'R',
        'ICORDS': 'G', 'IC': 'NC', 'ISYNC': 0, 'IMODE': 'P',
        'NBPR': 1, 'NBPC': 1, 'IMAG': '1.0 ', 'UDIDL': 0, 'IXSHDL': 0}
    _types = {
        '_Security': NITFSecurityTags,
        '_ImageComments': ImageComments,
        '_ImageBands': ImageBands}

    def __init__(self, **kwargs):
        super(ImageSegmentHeader, self).__init__(**kwargs)

    @property
    def Security(self):  # type: () -> NITFSecurityTags
        """NITFSecurityTags: the security tags instance"""
        return self._Security

    @Security.setter
    def Security(self, value):
        # noinspection PyAttributeOutsideInit
        self._Security = value

    @property
    def ImageComments(self):  # type: () -> ImageComments
        """ImageComments: the image comments instance"""
        return self._ImageComments

    @ImageComments.setter
    def ImageComments(self, value):
        # noinspection PyAttributeOutsideInit
        self._ImageComments = value

    @property
    def ImageBands(self):  # type: () -> ImageBands
        """ImageBands: the image bands instance"""
        return self._ImageBands

    @ImageBands.setter
    def ImageBands(self, value):
        # noinspection PyAttributeOutsideInit
        self._ImageBands = value


######
# Text segment header

class TextSegmentHeader(_HeaderScraper):
    """
    This requires an extension for essentially any non-trivial text segment
    """

    # TODO: LOW - this isn't quite right, and is certainly incomplete

    __slots__ = (
        'TE', 'TEXTID', 'TXTALVL',
        'TXTDT', 'TXTITL', '_Security',
        'ENCRYP', 'TXTFMT', 'TXSHDL', 'TXSOFL')
    _formats = {
        'TE': '2s', 'TEXTID': '7s', 'TXTALVL': '3d',
        'TXTDT': '14s', 'TXTITL': '80s', 'ENCRYP': '1d',
        'TXTFMT': '3s', 'TXSHDL': '5d', 'TXSOFL': '3d'}
    _defaults = {
        'TE': 'TE', 'TXTALVL': 0, 'TXTITL': '\x20',
        'ENCRYP': 0, 'TXSHDL': 0, 'TXSOFL': 0}
    _types = {
        '_Security': NITFSecurityTags,
    }

    def __init__(self, **kwargs):
        super(TextSegmentHeader, self).__init__(**kwargs)

    @classmethod
    def minimum_length(cls):
        return 118 + 167

    def __len__(self):
        return 118 + 167

    @property
    def Security(self):  # type: () -> NITFSecurityTags
        return self._Security

    @Security.setter
    def Security(self, value):
        # noinspection PyAttributeOutsideInit
        self._Security = value


######
# Data Extension header

class DataExtensionHeader(_HeaderScraper):
    """
    This requires an extension for essentially any non-trivial DES.
    """

    __slots__ = (
        'DE', 'DESID', 'DESVER', '_Security', 'DESSHL')
    _formats = {
        'DE': '2s', 'DESID': '25s', 'DESVER': '2d', 'DESSHL': '4d', }
    _defaults = {
        'DE': 'DE', }
    _types = {
        '_Security': NITFSecurityTags,
    }

    def __init__(self, **kwargs):
        if self._check_desid_for_value(kwargs, 'TRE_OVERFLOW'):
            raise ValueError('DESID="TRE_OVERFLOW" indicates specific use of DESTreOverflow type')
        super(DataExtensionHeader, self).__init__(**kwargs)

    @classmethod
    def minimum_length(cls):
        return 33 + 167

    def __len__(self):
        return 33 + 167 + self.DESSHL

    @property
    def Security(self):  # type: () -> NITFSecurityTags
        return self._Security

    @Security.setter
    def Security(self, value):
        # noinspection PyAttributeOutsideInit
        self._Security = value

    @staticmethod
    def _check_desid_for_value(kwargs, val):  # type: (dict, str) -> bool
        desid = kwargs.get('DESID', '')
        if isinstance(desid, bytes):
            desid.decode('utf-8')
        return desid.strip() == val

    @classmethod
    def from_bytes(cls, value, start, **kwargs):
        if value is None:
            if cls._check_desid_for_value(kwargs, 'TRE_OVERFLOW'):
                return DESTreOverflow(**kwargs)
            return cls(**kwargs)

        value = cls._validate(value, start)
        fields, _ = cls._parse_attributes(value, start)
        if cls._check_desid_for_value(fields, 'TRE_OVERFLOW'):
            # there were extra fields and the parsing was wrong, but that's okay
            return DESTreOverflow.from_bytes(value, start)
        return cls(**fields)

    def to_bytes(self, other_string=None):
        out = super(DataExtensionHeader, self).to_bytes()
        if self.DESSHL > 0:
            if other_string is None:
                raise ValueError('There should be a specific des subhead of length {} provided'.format(self.DESSHL))
            if isinstance(other_string, string_types):
                other_string = other_string.encode()
            if not isinstance(other_string, bytes):
                raise TypeError('The specific des subhead must be of type bytes or str, got {}'.format(type(other_string)))
            elif len(other_string) != self.DESSHL:
                raise ValueError(
                    'There should be a specific des subhead of length {} provided, '
                    'got one of length {}'.format(self.DESSHL, len(other_string)))
            out += other_string
        return out


class DESTreOverflow(DataExtensionHeader):
    __slots__ = (
        'DE', 'DESID', 'DESVER', '_Security',
        'DESOFLOW', 'DESITEM', 'DESSHL')
    _formats = {
        'DE': '2s', 'DESID': '25s', 'DESVER': '2d',
        'DESOFLOW': '6s', 'DESITEM': '3d', 'DESSHL': '4d', }
    _defaults = {
        'DE': 'DE', 'DESID': 'TRE_OVERFLOW', 'DESVER': 1, }
    _types = {
        '_Security': NITFSecurityTags,
    }

    @classmethod
    def minimum_length(cls):
        return 42 + 167

    def __len__(self):
        return 42 + 167 + self.DESSHL

    def to_bytes(self, other_string=None):
        # noinspection PyAttributeOutsideInit
        self.DESID = 'TRE_OVERFLOW'
        super(DESTreOverflow, self).to_bytes(other_string=other_string)


######
# The overall header

class NITFHeader(_HeaderScraper):
    """
    The NITF file header - described in SICD standard 2014-09-30, Volume II, page 17
    """

    __slots__ = (
        'FHDR', 'FVER', 'CLEVEL', 'STYPE',
        'OSTAID', 'FDT', 'FTITLE', '_Security',
        'FSCOP', 'FSCPYS', 'ENCRYP', 'FBKGC',
        'ONAME', 'OPHONE', 'FL', 'HL',
        '_ImageSegments', '_GraphicsSegments', 'NUMX',
        '_TextSegments', '_DataExtensions', '_ReservedExtensions',
        '_UserHeader', '_ExtendedHeader')
    # NB: NUMX is truly reserved for future use, and should always be 0
    _formats = {
        'FHDR': '4s', 'FVER': '5s', 'CLEVEL': '2d', 'STYPE': '4s',
        'OSTAID': '10s', 'FDT': '14s', 'FTITLE': '80s',
        'FSCOP': '5d', 'FSCPYS': '5d', 'ENCRYP': '1s', 'FBKGC': '3b',
        'ONAME': '24s', 'OPHONE': '18s', 'FL': '12d', 'HL': '6d',
        'NUMX': '3d', }
    _defaults = {
        'FHDR': 'NITF', 'FVER': '02.10', 'STYPE': 'BF01',
        'FSCOP': 0, 'FSCPYS': 0, 'ENCRYP': '0',
        'FBKGC': b'\x00\x00\x00', 'ONAME': '\x20', 'OPHONE': '\x20',
        'HL': 338, 'NUMX': 0, }
    _types = {
        '_Security': NITFSecurityTags,
        '_ImageSegments': _ItemArrayHeaders,
        '_GraphicsSegments': _ItemArrayHeaders,
        '_TextSegments': _ItemArrayHeaders,
        '_DataExtensions': _ItemArrayHeaders,
        '_ReservedExtensions': _ItemArrayHeaders,
        '_UserHeader': OtherHeader,
        '_ExtendedHeader': OtherHeader, }
    _args = {
        '_ImageSegments': {'subhead_len': 6, 'item_len': 10},
        '_GraphicsSegments': {'subhead_len': 4, 'item_len': 6},
        '_TextSegments': {'subhead_len': 4, 'item_len': 5},
        '_DataExtensions': {'subhead_len': 4, 'item_len': 9},
        '_ReservedExtensions': {'subhead_len': 4, 'item_len': 7},
    }

    def __init__(self, **kwargs):
        super(NITFHeader, self).__init__(**kwargs)
        self.HL = self.__len__()

    @property
    def Security(self):  # type: () -> NITFSecurityTags
        """NITFSecurityTags: the security tags instance"""
        return self._Security

    @Security.setter
    def Security(self, value):
        # noinspection PyAttributeOutsideInit
        self._Security = value

    @property
    def ImageSegments(self):  # type: () -> _ItemArrayHeaders
        return self._ImageSegments

    @ImageSegments.setter
    def ImageSegments(self, value):
        # noinspection PyAttributeOutsideInit
        self._ImageSegments = value

    @property
    def GraphicsSegments(self):  # type: () -> _ItemArrayHeaders
        return self._GraphicsSegments

    @GraphicsSegments.setter
    def GraphicsSegments(self, value):
        # noinspection PyAttributeOutsideInit
        self._GraphicsSegments = value

    @property
    def TextSegments(self):  # type: () -> _ItemArrayHeaders
        return self._TextSegments

    @TextSegments.setter
    def TextSegments(self, value):
        # noinspection PyAttributeOutsideInit
        self._TextSegments = value

    @property
    def DataExtensions(self):  # type: () -> _ItemArrayHeaders
        return self._DataExtensions

    @DataExtensions.setter
    def DataExtensions(self, value):
        # noinspection PyAttributeOutsideInit
        self._DataExtensions = value

    @property
    def ReservedExtensions(self):  # type: () -> _ItemArrayHeaders
        return self._ReservedExtensions

    @ReservedExtensions.setter
    def ReservedExtensions(self, value):
        # noinspection PyAttributeOutsideInit
        self._ReservedExtensions = value

    @property
    def UserHeader(self):  # type: () -> OtherHeader
        return self._UserHeader

    @UserHeader.setter
    def UserHeader(self, value):
        # noinspection PyAttributeOutsideInit
        self._UserHeader = value

    @property
    def ExtendedHeader(self):  # type: () -> OtherHeader
        return self._ExtendedHeader

    @ExtendedHeader.setter
    def ExtendedHeader(self, value):
        # noinspection PyAttributeOutsideInit
        self._ExtendedHeader = value


#####
# A general nitf header interpreter - intended for extension

class NITFDetails(object):
    """
    This class allows for somewhat general parsing of the header information in
    a NITF 2.1 file. It is expected that the text segment and data extension
    segments must be handled individually, probably by extending this class.
    """

    __slots__ = (
        '_file_name', '_nitf_header',
        'img_subheader_offsets', 'img_segment_offsets',
        'graphics_subheader_offsets', 'graphics_segment_offsets',
        'text_subheader_offsets', 'text_segment_offsets',
        'des_subheader_offsets', 'des_segment_offsets',
        'res_subheader_offsets', 'res_segment_offsets')

    def __init__(self, file_name):
        """

        Parameters
        ----------
        file_name : str
            file name for a NITF 2.1 file
        """

        self._file_name = file_name

        with open(file_name, mode='rb') as fi:
            # Read the first 9 bytes to verify NITF
            version_info = fi.read(9).decode('utf-8')
            if version_info != 'NITF02.10':
                raise IOError('Not a NITF 2.1 file.')
            # get the header length
            fi.seek(354)  # offset to first field of interest
            header_length = int_func(fi.read(6))
            # go back to the beginning of the file, and parse the whole header
            fi.seek(0)
            header_string = fi.read(header_length)
            self._nitf_header = NITFHeader.from_bytes(header_string, 0)

        curLoc = self._nitf_header.HL
        # populate image segment offset information
        curLoc, self.img_subheader_offsets, self.img_segment_offsets = self._element_offsets(
            curLoc, self._nitf_header.ImageSegments)
        # populate graphics segment offset information
        curLoc, self.graphics_subheader_offsets, self.graphics_segment_offsets = self._element_offsets(
            curLoc, self._nitf_header.GraphicsSegments)
        # populate text segment offset information
        curLoc, self.text_subheader_offsets, self.text_segment_offsets = self._element_offsets(
            curLoc, self._nitf_header.TextSegments)
        # populate data extension offset information
        curLoc, self.des_subheader_offsets, self.des_segment_offsets = self._element_offsets(
            curLoc, self._nitf_header.DataExtensions)
        # populate data extension offset information
        curLoc, self.res_subheader_offsets, self.res_segment_offsets = self._element_offsets(
            curLoc, self._nitf_header.ReservedExtensions)

    @staticmethod
    def _element_offsets(curLoc, item_array_details):
        # type: (int, _ItemArrayHeaders) -> Tuple[int, Union[None, numpy.ndarray], Union[None, numpy.ndarray]]
        subhead_sizes = item_array_details.subhead_sizes
        item_sizes = item_array_details.item_sizes
        if subhead_sizes.size == 0:
            return curLoc, None, None

        subhead_offsets = numpy.full(subhead_sizes.shape, curLoc, dtype=numpy.int64)
        subhead_offsets[1:] += numpy.cumsum(subhead_sizes[:-1]) + numpy.cumsum(item_sizes[:-1])
        item_offsets = subhead_offsets + subhead_sizes
        curLoc = item_offsets[-1] + item_sizes[-1]
        return curLoc, subhead_offsets, item_offsets

    @property
    def file_name(self):
        """str: the file name."""
        return self._file_name

    @property
    def nitf_header(self):  # type: () -> NITFHeader
        """NITFHeader: the nitf header object"""
        return self._nitf_header
