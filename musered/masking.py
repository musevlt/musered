import logging
import numpy as np
import warnings

from astropy.stats import sigma_clipped_stats
from mpdaf.obj import Image
from scipy import ndimage as ndi


def mask_sources(image, outfile=None, iterations=2, outimage=None,
                 plot=False, sigma=3., opening_iterations=0):
    logger = logging.getLogger(__name__)
    try:
        import photutils
    except ImportError:
        logger.critical('photutils is required and was not found.')
        raise

    logger.info('Reading image %s', image)
    im = image if isinstance(image, Image) else Image(image)

    with warnings.catch_warnings():
        warnings.simplefilter('ignore', category=RuntimeWarning)
        mean, median, std = sigma_clipped_stats(im.data, sigma=3.0)
        logger.info('mean: %s, median: %s, std: %s', mean, median, std)
        threshold = median + (std * sigma)
        segm_img = photutils.detect_sources(im.data, threshold, npixels=5)

    # turn segm_img into a mask
    try:
        # photutils 0.1
        mask = segm_img.astype(np.bool)
    except AttributeError:
        # photutils 0.2+
        mask = segm_img.data.astype(np.bool)

    if opening_iterations > 0:
        struct = ndi.generate_binary_structure(2, 2)
        mask = ndi.binary_opening(mask, structure=struct,
                                  iterations=opening_iterations)

    if iterations > 0:
        struct = ndi.generate_binary_structure(2, 2)
        mask = ndi.binary_dilation(mask, structure=struct,
                                   iterations=iterations)

    im_mask = Image(data=mask, dtype=int, wcs=im.wcs, copy=False)
    if outfile:
        im_mask.write(outfile, savemask='none')

    if plot or outimage:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(2, 2, figsize=(12, 12), tight_layout=True)
        ax = ax.ravel()
        plt.set_cmap('coolwarm')
        vmin, vmax = mean - 1, mean + 1
        im.plot(ax=ax[0], scale='linear', vmin=vmin, vmax=vmax, colorbar='v')
        ax[1].imshow(segm_img, origin='lower', interpolation='nearest')
        ax[1].set_title('Segmentation map')
        ax[2].imshow(mask, interpolation='nearest', cmap='binary',
                     origin='lower')
        ax[2].set_title('Mask')
        im_masked = im.copy()
        im_masked.mask_selection(mask)
        im_masked.plot(ax=ax[3], scale='linear', vmin=vmin, vmax=vmax,
                       title='Masked image')

        if plot:
            plt.show()
        if outimage:
            fig.savefig(outimage)

    return im_mask
