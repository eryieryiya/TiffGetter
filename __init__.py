# 点数据到TIFF影像处理包

from .point_reader import read_points
from .buffer_generator import generate_buffers, create_square_buffer
from .satellite_processor import SatelliteToTiffConverter
from .config import *

__version__ = "1.0.0"
__author__ = "Point KML2TIFF Team"
__description__ = "从点数据到带地理参考TIFF影像的完整处理流程"