# ######################################################################
# Copyright (c) 2014, Brookhaven Science Associates, Brookhaven        #
# National Laboratory. All rights reserved.                            #
#                                                                      #
# Developed at the NSLS-II, Brookhaven National Laboratory             #
# Developed by Sameera K. Abeykoon, January 2016                       #
#                                                                      #
# Redistribution and use in source and binary forms, with or without   #
# modification, are permitted provided that the following conditions   #
# are met:                                                             #
#                                                                      #
# * Redistributions of source code must retain the above copyright     #
#   notice, this list of conditions and the following disclaimer.      #
#                                                                      #
# * Redistributions in binary form must reproduce the above copyright  #
#   notice this list of conditions and the following disclaimer in     #
#   the documentation and/or other materials provided with the         #
#   distribution.                                                      #
#                                                                      #
# * Neither the name of the Brookhaven Science Associates, Brookhaven  #
#   National Laboratory nor the names of its contributors may be used  #
#   to endorse or promote products derived from this software without  #
#   specific prior written permission.                                 #
#                                                                      #
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS  #
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT    #
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS    #
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE       #
# COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT,           #
# INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES   #
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR   #
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)   #
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,  #
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OTHERWISE) ARISING   #
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE   #
# POSSIBILITY OF SUCH DAMAGE.                                          #
########################################################################

"""
This module is for functions specific to mask or threshold an image
basically to clean images
"""

from __future__ import absolute_import, division, print_function
import numpy as np

import logging
logger = logging.getLogger(__name__)


def bad_to_nan_gen(images, bad):
    """
    Convert the images marked as "bad" in `bad` by their index in
    images into a np.nan array

    Parameters
    ----------
    images : iterable
        Iterable of 2-D arrays
    bad : list
        List of integer indices into the `images` parameter that mark those
        images as "bad".

    Yields
    ------
    img : array
        if image is bad it will convert to np.nan array otherwise no
        change to the array
    """
    ret_val = None
    for n, im in enumerate(images):
        if n in bad:
            if ret_val is None:
                ret_val = np.empty(im.shape)
                ret_val[:] = np.nan
            yield ret_val
        else:
            yield im


def threshold_mask(images, threshold, mask=None):
    """
    This generator sets all pixels whose value is greater than `threshold`
    to 0 and yields the thresholded images out

    Parameters
    ----------
    images : iterable
        Iterable of 2-D arrays
    threshold : float
        threshold value to remove the hot spots in the image
    mask : array
        array with values above the threshold marked as 0 and values
        below marked as 1.
        shape is (num_columns, num_rows) of the image, optional None

    Yields
    -------
    mask : array
        array with values above the threshold marked as 0 and values
        below marked as 1.
        shape is (num_columns, num_rows) of the image
    """
    if mask is None:
        mask = np.ones_like(images[0])
    for im in images:
        bad_pixels = np.where(im >= threshold)
        if len(bad_pixels[0]) != 0:
            mask[bad_pixels] = 0
        yield mask
