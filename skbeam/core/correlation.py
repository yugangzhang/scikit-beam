# ######################################################################
# Developed at the NSLS-II, Brookhaven National Laboratory             #
# Developed by Sameera K. Abeykoon, February 2014                      #
#                                                                      #
# Copyright (c) 2014, Brookhaven Science Associates, Brookhaven        #
# National Laboratory. All rights reserved.                            #
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

This module is for functions specific to time correlation

"""
from __future__ import absolute_import, division, print_function
from .utils import multi_tau_lags
from .roi import extract_label_indices
from collections import namedtuple
import numpy as np

import logging
logger = logging.getLogger(__name__)


def _one_time_process(buf, G, past_intensity_norm, future_intensity_norm,
                      label_array, num_bufs, num_pixels, img_per_level,
                      level, buf_no, norm, lev_len):
    """Reference implementation of the inner loop of multi-tau one time
    correlation

    This helper function calculates G, past_intensity_norm and
    future_intensity_norm at each level, symmetric normalization is used.

    .. warning :: This modifies inputs in place.

    Parameters
    ----------
    buf : array
        image data array to use for correlation
    G : array
        matrix of auto-correlation function without normalizations
    past_intensity_norm : array
        matrix of past intensity normalizations
    future_intensity_norm : array
        matrix of future intensity normalizations
    label_array : array
        labeled array where all nonzero values are ROIs
    num_bufs : int, even
        number of buffers(channels)
    num_pixels : array
        number of pixels in certain ROI's
        ROI's, dimensions are : [number of ROI's]X1
    img_per_level : array
        to track how many images processed in each level
    level : int
        the current multi-tau level
    buf_no : int
        the current buffer number
    norm : dict
        to track bad images
    lev_len : array
        length of each level

    Notes
    -----
    .. math::
        G = <I(\tau)I(\tau + delay)>
    .. math::
        past_intensity_norm = <I(\tau)>
    .. math::
        future_intensity_norm = <I(\tau + delay)>
    """
    img_per_level[level] += 1
    # in multi-tau correlation, the subsequent levels have half as many
    # buffers as the first
    i_min = num_bufs // 2 if level else 0
    for i in range(i_min, min(img_per_level[level], num_bufs)):
        # compute the index into the autocorrelation matrix
        t_index = level * num_bufs / 2 + i
        delay_no = (buf_no - i) % num_bufs

        # get the images for correlating
        past_img = buf[level, delay_no]
        future_img = buf[level, buf_no]

        # find the normalization that can work both for bad_images
        #  and good_images
        ind = int(t_index - lev_len[:level].sum())
        normalize = img_per_level[level] - i - norm[level+1][ind]

        # take out the past_ing and future_img created using bad images
        # (bad images are converted to np.nan array)
        if np.isnan(past_img).any() or np.isnan(future_img).any():
            norm[level + 1][ind] += 1
        else:
            for w, arr in zip([past_img*future_img, past_img, future_img],
                              [G, past_intensity_norm, future_intensity_norm]):
                binned = np.bincount(label_array, weights=w)[1:]
                arr[t_index] += ((binned / num_pixels -
                                  arr[t_index]) / normalize)
    return None  # modifies arguments in place!


results = namedtuple(
    'correlation_results',
    ['g2', 'lag_steps', 'internal_state']
)

_internal_state = namedtuple(
    'correlation_state',
    ['buf',
     'G',
     'past_intensity',
     'future_intensity',
     'img_per_level',
     'label_array',
     'track_level',
     'cur',
     'pixel_list',
     'num_pixels',
     'lag_steps',
     'norm',
     'lev_len']
)

_two_time_internal_state = namedtuple(
    'two_time_correlation_state',
    ['buf',
     'img_per_level',
     'label_array',
     'track_level',
     'cur',
     'pixel_list',
     'num_pixels',
     'lag_steps',
     'g2',
     'count_level',
     'current_img_time',
     'time_ind',
     'norm',
     'lev_len']
)


def _init_state_one_time(num_levels, num_bufs, labels):
    """Initialize a stateful namedtuple for the generator-based multi-tau
     for one time correlation

    Parameters
    ----------
    num_levels : int
    num_bufs : int
    labels : array
        Two dimensional labeled array that contains ROI information

    Returns
    -------
    internal_state : namedtuple
        The namedtuple that contains all the state information that
        `lazy_one_time` requires so that it can be used to pick up
         processing after it was interrupted
    """
    (label_array, pixel_list, num_rois, num_pixels, lag_steps, buf,
     img_per_level, track_level, cur, norm,
     lev_len) = _validate_and_transform_inputs(num_bufs, num_levels, labels)

    # G holds the un normalized auto- correlation result. We
    # accumulate computations into G as the algorithm proceeds.
    G = np.zeros(((num_levels + 1) * num_bufs / 2, num_rois),
                 dtype=np.float64)
    # matrix for normalizing G into g2
    past_intensity = np.zeros_like(G)
    # matrix for normalizing G into g2
    future_intensity = np.zeros_like(G)

    return _internal_state(
        buf,
        G,
        past_intensity,
        future_intensity,
        img_per_level,
        label_array,
        track_level,
        cur,
        pixel_list,
        num_pixels,
        lag_steps,
        norm,
        lev_len,
    )


def lazy_one_time(image_iterable, num_levels, num_bufs, labels,
                  internal_state=None):
    """Generator implementation of 1-time multi-tau correlation

    If you do not want multi-tau correlation, set num_levels to 1 and
    num_bufs to the number of images you wish to correlate

    Parameters
    ----------
    image_iterable : iterable of 2D arrays
    num_levels : int
        how many generations of downsampling to perform, i.e., the depth of
        the binomial tree of averaged frames
    num_bufs : int, must be even
        maximum lag step to compute in each generation of downsampling
    labels : array
        Labeled array of the same shape as the image stack.
        Each ROI is represented by sequential integers starting at one.  For
        example, if you have four ROIs, they must be labeled 1, 2, 3,
        4. Background is labeled as 0
    internal_state : namedtuple, optional
        internal_state is a bucket for all of the internal state of the
        generator. It is part of the `results` object that is yielded from
        this generator

    Yields
    ------
    namedtuple
        A `results` object is yielded after every image has been processed.
        This `reults` object contains, in this order:
        - `g2`: the normalized correlation
          shape is (len(lag_steps), num_rois)
        - `lag_steps`: the times at which the correlation was computed
        - `_internal_state`: all of the internal state. Can be passed back in
          to `lazy_one_time` as the `internal_state` parameter

    Notes
    -----
    The normalized intensity-intensity time-autocorrelation function
    is defined as

    .. math::
        g_2(q, t') = \\frac{<I(q, t)I(q, t + t')> }{<I(q, t)>^2}

        t' > 0

    Here, ``I(q, t)`` refers to the scattering strength at the momentum
    transfer vector ``q`` in reciprocal space at time ``t``, and the brackets
    ``<...>`` refer to averages over time ``t``. The quantity ``t'`` denotes
    the delay time

    This implementation is based on published work. [1]_

    References
    ----------
    .. [1] D. Lumma, L. B. Lurio, S. G. J. Mochrie and M. Sutton,
        "Area detector based photon correlation in the regime of
        short data batches: Data reduction for dynamic x-ray
        scattering," Rev. Sci. Instrum., vol 71, p 3274-3289, 2000.
    """

    if internal_state is None:
        internal_state = _init_state_one_time(num_levels, num_bufs, labels)
    # create a shorthand reference to the results and state named tuple
    s = internal_state

    # iterate over the images to compute multi-tau correlation
    for image in image_iterable:
        # Compute the correlations for all higher levels.
        level = 0

        # increment buffer
        s.cur[0] = (1 + s.cur[0]) % num_bufs

        # Put the ROI pixels into the ring buffer.
        s.buf[0, s.cur[0] - 1] = np.ravel(image)[s.pixel_list]
        buf_no = s.cur[0] - 1
        # Compute the correlations between the first level
        # (undownsampled) frames. This modifies G,
        # past_intensity, future_intensity,
        # and img_per_level in place!
        _one_time_process(s.buf, s.G, s.past_intensity, s.future_intensity,
                          s.label_array, num_bufs, s.num_pixels,
                          s.img_per_level, level, buf_no, s.norm, s.lev_len)

        # check whether the number of levels is one, otherwise
        # continue processing the next level
        processing = num_levels > 1

        level = 1
        while processing:
            if not s.track_level[level]:
                s.track_level[level] = True
                processing = False
            else:
                prev = (1 + (s.cur[level - 1] - 2) % num_bufs)
                s.cur[level] = (
                    1 + s.cur[level] % num_bufs)

                s.buf[level, s.cur[level] - 1] = ((
                        s.buf[level - 1, prev - 1] +
                        s.buf[level - 1, s.cur[level - 1] - 1]) / 2)

                # make the track_level zero once that level is processed
                s.track_level[level] = False

                # call processing_func for each multi-tau level greater
                # than one. This is modifying things in place. See comment
                # on previous call above.
                buf_no = s.cur[level] - 1
                _one_time_process(s.buf, s.G, s.past_intensity,
                                  s.future_intensity, s.label_array, num_bufs,
                                  s.num_pixels, s.img_per_level, level, buf_no,
                                  s.norm, s.lev_len)
                level += 1

                # Checking whether there is next level for processing
                processing = level < num_levels

        # If any past intensities are zero, then g2 cannot be normalized at
        # those levels. This if/else code block is basically preventing
        # divide-by-zero errors.
        if len(np.where(s.past_intensity == 0)[0]) != 0:
            g_max = np.where(s.past_intensity == 0)[0][0]
        else:
            g_max = s.past_intensity.shape[0]

        g2 = (s.G[:g_max] / (s.past_intensity[:g_max] *
                             s.future_intensity[:g_max]))
        yield results(g2, s.lag_steps[:g_max], s)


def multi_tau_auto_corr(num_levels, num_bufs, labels, images):
    """Wraps generator implementation of multi-tau

    Original code(in Yorick) for multi tau auto correlation
    author: Mark Sutton

    For parameter description, please reference the docstring for
    lazy_one_time. Note that there is an API difference between this function
    and `lazy_one_time`. The `images` arugment is at the end of this function
    signature here for backwards compatibility, but is the first argument in
    the `lazy_one_time()` function. The semantics of the variables remain
    unchanged.
    """
    gen = lazy_one_time(images, num_levels, num_bufs, labels)
    for result in gen:
        pass
    return result.g2, result.lag_steps


def auto_corr_scat_factor(lags, beta, relaxation_rate, baseline=1):
    """
    This model will provide normalized intensity-intensity time
    correlation data to be minimized.

    Parameters
    ----------
    lags : array
        delay time
    beta : float
        optical contrast (speckle contrast), a sample-independent
        beamline parameter
    relaxation_rate : float
        relaxation time associated with the samples dynamics.
    baseline : float, optional
        baseline of one time correlation
        equal to one for ergodic samples

    Returns
    -------
    g2 : array
        normalized intensity-intensity time autocorreltion

    Notes :
    -------
    The intensity-intensity autocorrelation g2 is connected to the intermediate
    scattering factor(ISF) g1

    .. math::
        g_2(q, \\tau) = \\beta_1[g_1(q, \\tau)]^{2} + g_\infty

    For a system undergoing  diffusive dynamics,
    .. math::
        g_1(q, \\tau) = e^{-\gamma(q) \\tau}
    .. math::
       g_2(q, \\tau) = \\beta_1 e^{-2\gamma(q) \\tau} + g_\infty

    These implementation are based on published work. [1]_

    References
    ----------
    .. [1] L. Li, P. Kwasniewski, D. Orsi, L. Wiegart, L. Cristofolini,
       C. Caronna and A. Fluerasu, " Photon statistics and speckle
       visibility spectroscopy with partially coherent X-rays,"
       J. Synchrotron Rad. vol 21, p 1288-1295, 2014

    """
    return beta * np.exp(-2 * relaxation_rate * lags) + baseline


def two_time_corr(labels, images, num_frames, num_bufs, num_levels=1):
    """Wraps generator implementation of multi-tau two time correlation

    This function computes two-time correlation
    Original code : author: Yugang Zhang

    Returns
    -------
    results : namedtuple

    For parameter definition, see the docstring for the `lazy_two_time()`
    function in this module
    """
    gen = lazy_two_time(labels, images, num_frames, num_bufs, num_levels)
    for result in gen:
        pass
    return two_time_state_to_results(result)


def lazy_two_time(labels, images, num_frames, num_bufs, num_levels=1,
                  two_time_internal_state=None):
    """ Generator implementation of two-time correlation

    If you do not want multi-tau correlation, set num_levels to 1 and
    num_bufs to the number of images you wish to correlate

    Multi-tau correlation uses a scheme to achieve long-time correlations
    inexpensively by downsampling the data, iteratively combining successive
    frames.

    The longest lag time computed is num_levels * num_bufs.
    ** see comments on multi_tau_auto_corr

    Parameters
    ----------
    labels : array
        labeled array of the same shape as the image stack;
        each ROI is represented by a distinct label (i.e., integer)
    images : iterable of 2D arrays
        dimensions are: (rr, cc), iterable of 2D arrays
    num_frames : int
        number of images to use
        default is number of images
    num_bufs : int, must be even
        maximum lag step to compute in each generation of
        downsampling
    num_levels : int, optional
        how many generations of downsampling to perform, i.e.,
        the depth of the binomial tree of averaged frames
        default is one

    Yields
    ------
    namedtuple
        A ``results`` object is yielded after every image has been processed.
        This `reults` object contains, in this order:
        - ``g2``: the normalized correlation
          shape is (num_rois, len(lag_steps), len(lag_steps))
        - ``lag_steps``: the times at which the correlation was computed
        - ``_internal_state``: all of the internal state. Can be passed back in
          to ``lazy_one_time`` as the ``internal_state`` parameter

    Notes
    -----
    The two-time correlation function is defined as

    .. math::
        C(q,t_1,t_2) = \\frac{<I(q,t_1)I(q,t_2)>}{<I(q, t_1)><I(q,t_2)>}

    Here, the ensemble averages are performed over many pixels of detector,
    all having the same ``q`` value. The average time or age is equal to
    ``(t1+t2)/2``, measured by the distance along the ``t1 = t2`` diagonal.
    The time difference ``t = |t1 - t2|``, with is distance from the
    ``t1 = t2`` diagonal in the perpendicular direction.
    In the equilibrium system, the two-time correlation functions depend only
    on the time difference ``t``, and hence the two-time correlation contour
    lines are parallel.

    References
    ----------

    .. [1]
        A. Fluerasu, A. Moussaid, A. Mandsen and A. Schofield, "Slow dynamics
        and aging in collodial gels studied by x-ray photon correlation
        spectroscopy," Phys. Rev. E., vol 76, p 010401(1-4), 2007.
    """
    if two_time_internal_state is None:
        two_time_internal_state = _init_state_two_time(num_levels, num_bufs,
                                                       labels, num_frames)
    # create a shorthand reference to the results and state named tuple
    s = two_time_internal_state

    for img in images:
        s.cur[0] = (1 + s.cur[0]) % num_bufs  # increment buffer

        s.count_level[0] = 1 + s.count_level[0]

        # get the current image time
        s = s._replace(current_img_time=(s.current_img_time + 1))

        # Put the image into the ring buffer.
        s.buf[0, s.cur[0] - 1] = (np.ravel(img))[s.pixel_list]

        # Compute the two time correlations between the first level
        # (undownsampled) frames. two_time and img_per_level in place!
        _two_time_process(s.buf, s.g2, s.label_array, num_bufs,
                          s.num_pixels, s.img_per_level, s.lag_steps,
                          s.current_img_time,
                          level=0, buf_no=s.cur[0] - 1)

        # time frame for each level
        s.time_ind[0].append(s.current_img_time)

        # check whether the number of levels is one, otherwise
        # continue processing the next level
        processing = num_levels > 1

        # Compute the correlations for all higher levels.
        level = 1
        while processing:
            if not s.track_level[level]:
                s.track_level[level] = 1
                processing = False
            else:
                prev = 1 + (s.cur[level - 1] - 2) % num_bufs
                s.cur[level] = 1 + s.cur[level] % num_bufs
                s.count_level[level] = 1 + s.count_level[level]

                s.buf[level, s.cur[level] - 1] = (s.buf[level - 1, prev - 1] +
                                                  s.buf[level - 1,
                                                  s.cur[level - 1] - 1])/2

                t1_idx = (s.count_level[level] - 1) * 2

                current_img_time = ((s.time_ind[level - 1])[t1_idx] +
                                    (s.time_ind[level - 1])[t1_idx + 1])/2.

                # time frame for each level
                s.time_ind[level].append(current_img_time)

                # make the track_level zero once that level is processed
                s.track_level[level] = 0

                # call the _two_time_process function for each multi-tau level
                # for multi-tau levels greater than one
                # Again, this is modifying things in place. See comment
                # on previous call above.
                _two_time_process(s.buf, s.g2, s.label_array, num_bufs,
                                  s.num_pixels, s.img_per_level, s.lag_steps,
                                  current_img_time,
                                  level=level, buf_no=s.cur[level]-1)
                level += 1

                # Checking whether there is next level for processing
                processing = level < num_levels
        yield s


def two_time_state_to_results(state):
    """Convert the internal state of the two time generator into usable results

    Parameters
    ----------
    state : namedtuple
        The internal state that is yielded from `lazy_two_time`

    Returns
    -------
    results : namedtuple
        A results object that contains the two time correlation results
        and the lag steps
    """
    for q in range(np.max(state.label_array)):
        x0 = (state.g2)[q, :, :]
        (state.g2)[q, :, :] = (np.tril(x0) + np.tril(x0).T -
                               np.diag(np.diag(x0)))
    return results(state.g2, state.lag_steps, state)


def _two_time_process(buf, g2, label_array, num_bufs, num_pixels,
                      img_per_level, lag_steps, current_img_time,
                      level, buf_no):
    """
    Parameters
    ----------
    buf: array
        image data array to use for two time correlation
    g2: array
        two time correlation matrix
        shape (number of labels(ROI), number of frames, number of frames)
    label_array: array
        Elements not inside any ROI are zero; elements inside each
        ROI are 1, 2, 3, etc. corresponding to the order they are specified
        in edges and segments
    num_bufs: int, even
        number of buffers(channels)
    num_pixels : array
        number of pixels in certain ROI's
        ROI's, dimensions are len(np.unique(label_array))
    img_per_level: array
        to track how many images processed in each level
    lag_steps : array
        delay or lag steps for the multiple tau analysis
        shape num_levels
    current_img_time : int
        the current image number
    level : int
        the current multi-tau level
    buf_no : int
        the current buffer number
    """
    img_per_level[level] += 1

    # in multi-tau correlation other than first level all other levels
    #  have to do the half of the correlation
    if level == 0:
        i_min = 0
    else:
        i_min = num_bufs//2

    for i in range(i_min, min(img_per_level[level], num_bufs)):
        t_index = level*num_bufs/2 + i

        delay_no = (buf_no - i) % num_bufs

        past_img = buf[level, delay_no]
        future_img = buf[level, buf_no]

        #  get the matrix of correlation function without normalizations
        tmp_binned = (np.bincount(label_array,
                                  weights=past_img*future_img)[1:])
        # get the matrix of past intensity normalizations
        pi_binned = (np.bincount(label_array,
                                 weights=past_img)[1:])

        # get the matrix of future intensity normalizations
        fi_binned = (np.bincount(label_array,
                                 weights=future_img)[1:])

        tind1 = (current_img_time - 1)

        tind2 = (current_img_time - lag_steps[t_index] - 1)

        if not isinstance(current_img_time, int):
            nshift = 2**(level-1)
            for i in range(-nshift+1, nshift+1):
                g2[:, int(tind1+i),
                   int(tind2+i)] = (tmp_binned/(pi_binned *
                                                fi_binned))*num_pixels
        else:
            g2[:, tind1, tind2] = tmp_binned/(pi_binned * fi_binned)*num_pixels


def _init_state_two_time(num_levels, num_bufs, labels, num_frames):
    """Initialize a stateful namedtuple for two time correlation

    Parameters
    ----------
    num_levels : int
    num_bufs : int
    labels : array
        Two dimensional labeled array that contains ROI information
    num_frames : int
        number of images to use
        default is number of images
    Returns
    -------
    internal_state : namedtuple
        The namedtuple that contains all the state information that
        `lazy_two_time` requires so that it can be used to pick up processing
        after it was interrupted
    """
    (label_array, pixel_list, num_rois, num_pixels, lag_steps,
     buf, img_per_level, track_level, cur, norm,
     lev_len) = _validate_and_transform_inputs(num_bufs, num_levels, labels)

    # to count images in each level
    count_level = np.zeros(num_levels, dtype=np.int64)

    # current image time
    current_img_time = 0

    # generate a time frame for each level
    time_ind = {key: [] for key in range(num_levels)}

    # two time correlation results (array)
    g2 = np.zeros((num_rois, num_frames, num_frames), dtype=np.float64)

    return _two_time_internal_state(
        buf,
        img_per_level,
        label_array,
        track_level,
        cur,
        pixel_list,
        num_pixels,
        lag_steps,
        g2,
        count_level,
        current_img_time,
        time_ind,
        norm,
        lev_len,
    )


def _validate_and_transform_inputs(num_bufs, num_levels, labels):
    """
    This is a helper function to validate inputs and create initial state
    inputs for both one time and two time correlation

    Parameters
    ----------
    num_bufs : int
    num_levels : int
    labels : array
        labeled array of the same shape as the image stack;
        each ROI is represented by a distinct label (i.e., integer)

    Returns
    -------
    label_array : array
        labels of the required region of interests(ROI's)
    pixel_list : array
        1D array of indices into the raveled image for all
        foreground pixels (labeled nonzero)
        e.g., [5, 6, 7, 8, 14, 15, 21, 22]
    num_rois : int
        number of region of interests (ROI)
    num_pixels : array
        number of pixels in each ROI
    lag_steps : array
        the times at which the correlation was computed
    buf : array
        image data for correlation
    img_per_level : array
        to track how many images processed in each level
    track_level : array
        to track processing each level
    cur : array
        to increment the buffer
    norm : dict
        to track bad images
    lev_len : array
        length of each levels
    """
    if num_bufs % 2 != 0:
        raise ValueError("There must be an even number of `num_bufs`. You "
                         "provided %s" % num_bufs)
    label_array, pixel_list = extract_label_indices(labels)

    # map the indices onto a sequential list of integers starting at 1
    label_mapping = {label: n+1
                     for n, label in enumerate(np.unique(label_array))}
    # remap the label array to go from 1 -> max(_labels)
    for label, n in label_mapping.items():
        label_array[label_array == label] = n

    # number of ROI's
    num_rois = len(label_mapping)

    # stash the number of pixels in the mask
    num_pixels = np.bincount(label_array)[1:]

    # Convert from num_levels, num_bufs to lag frames.
    tot_channels, lag_steps, dict_lag = multi_tau_lags(num_levels, num_bufs)

    # these norm and lev_len will help to find the one time correlation
    # normalization norm will updated when there is a bad image
    norm = {key: [0] * len(dict_lag[key]) for key in (dict_lag.keys())}
    lev_len = np.array([len(dict_lag[i]) for i in (dict_lag.keys())])

    # Ring buffer, a buffer with periodic boundary conditions.
    # Images must be keep for up to maximum delay in buf.
    buf = np.zeros((num_levels, num_bufs, len(pixel_list)),
                   dtype=np.float64)
    # to track how many images processed in each level
    img_per_level = np.zeros(num_levels, dtype=np.int64)
    # to track which levels have already been processed
    track_level = np.zeros(num_levels, dtype=bool)
    # to increment buffer
    cur = np.ones(num_levels, dtype=np.int64)

    return (label_array, pixel_list, num_rois, num_pixels,
            lag_steps, buf, img_per_level, track_level, cur,
            norm, lev_len)


def one_time_from_two_time(two_time_corr):
    """
    This will provide the one-time correlation data from two-time
    correlation data.

    Parameters
    ----------
    two_time_corr : array
        matrix of two time correlation
        shape (number of labels(ROI's), number of frames, number of frames)

    Returns
    -------
    one_time_corr : array
        matrix of one time correlation
        shape (number of labels(ROI's), number of frames)
    """

    one_time_corr = np.zeros((two_time_corr.shape[0], two_time_corr.shape[2]))
    for g in two_time_corr:
        for j in range(two_time_corr.shape[2]):
            one_time_corr[:, j] = np.trace(g, offset=j)/two_time_corr.shape[2]
    return one_time_corr
