import os
import time
import logging
import numpy

from . import unittest

from sarpy.io.complex.radarsat import RadarSatReader
from sarpy.deprecated.io.complex.radarsat import Reader as DepReader


def generic_rs2_test(instance, test_root, test_file):
    assert isinstance(instance, unittest.TestCase)

    with instance.subTest(msg='establish rs2 reader for file {}'.format(test_root)):
        reader = RadarSatReader(test_root)

    with instance.subTest(msg='establish deprecated rs2 reader for file {}'.format(test_root)):
        dep_reader = DepReader(test_file)

    for i in range(len(reader.sicd_meta)):
        data_new = reader[:5, :5, i]
        data_dep = dep_reader.read_chip[i](numpy.array((0, 5, 1), dtype=numpy.int64), numpy.array((0, 5, 1), dtype=numpy.int64))
        comp = numpy.abs(data_new - data_dep)
        same = numpy.all(comp < 1e-10)
        with instance.subTest(msg='rs2 fetch test for file {}'.format(test_root)):
            instance.assertTrue(same, msg='index {} fetch comparison failed'.format(i))
            if not same:
                logging.error('index = {}\nnew data = {}\nold data = {}'.format(i, data_new, data_dep))


class TestRS2Reader(unittest.TestCase):

    @classmethod
    def setUp(cls):
        cls.rs2_root = os.path.expanduser('~/Desktop/sarpy_testing/RS2/')

    def test_reader(self):
        tested = 0
        for fil in [
                'RS2_OK98614_PK861734_DK794020_FQ12W_20180917_234007_HH_VV_HV_VH_SLC', ]:
            test_root = os.path.join(self.rs2_root, fil)
            test_file = os.path.join(test_root, 'product.xml')

            if os.path.exists(test_file):
                tested += 1
                generic_rs2_test(self, test_root, test_file)
            else:
                logging.info('No file {} found'.format(test_file))

        self.assertTrue(tested > 0, msg="No files for testing found")
