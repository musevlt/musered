import numpy as np
import os
from astropy.io import fits
from astropy.table import Table
from mpdaf.obj import Cube, CubeList

from .recipe import PythonRecipe
from .science import MAKECUBE
from ..utils import get_exp_name


class SUPERFLAT(PythonRecipe):

    recipe_name = 'superflat'
    DPR_TYPE = 'DATACUBE_FINAL'
    output_dir = 'superflat'
    output_frames = ['DATACUBE_FINAL', 'IMAGE_FOV', 'SUPERFLAT']
    version = '0.1'
    # Save the V,R,I images
    default_params = {'filter': 'white,Johnson_V,Cousins_R,Cousins_I'}

    @property
    def calib_frames(self):
        return ['FILTER_LIST', 'OUTPUT_WCS', 'OFFSET_LIST']

    def _run(self, flist, *args, exposures=None, name=None, **kwargs):
        hdr = fits.getheader(flist[0])
        ra, dec = hdr['RA'], hdr['DEC']

        # 1. Run scipost for all exposures used to build the superflat
        run = exposures[exposures['name'] == name]['run'][0]
        exps = exposures[exposures['run'] == run]

        # Fix the RA/DEC/DROT values for all exposures to the values of the
        # reference exp. Take into account the offset of the exposure, as we
        # need the superflat to be aligned with the exposure. The offset is
        # applied them directly to the RA/DEC values, otherwise the DRS checks
        # the exposure name.
        if 'OFFSET_LIST' in kwargs:
            offsets = Table.read(kwargs['OFFSET_LIST'])
            offsets = offsets[offsets['DATE_OBS'] == hdr['DATE-OBS']]
            ra -= offsets['RA_OFFSET'][0]
            dec -= offsets['DEC_OFFSET'][0]

        os.environ['MUSE_SUPERFLAT_POS'] = ','.join(
            map(str, (ra, dec, hdr['ESO INS DROT POSANG'])))

        make_cube = MAKECUBE()
        recipe_kw = {key: kwargs[key] for key in ('FILTER_LIST', 'OUTPUT_WCS')
                     if key in kwargs}

        cubelist = []
        for exp in exps:
            output_dir = os.path.join(self.output_dir, 'cubes', exp['name'])
            outname = f'{output_dir}/DATACUBE_FINAL.fits'
            if os.path.exists(outname):
                self.logger.info('%s already processed', exp['name'])
            else:
                self.logger.info('processing %s', exp['name'])
                make_cube.run(exp['path'], output_dir=output_dir,
                              filter='white', **recipe_kw)
            cubelist.append(outname)

        # Get list of processed cubes
        # glob(f'{recipe.output_dir}/{out_frame}*.fits')

        # FIXME - Keep and use variance ?

        # 2. Combine exposures to obtain the superflat
        cubes = CubeList(cubelist)
        supercube, _, _ = cubes.combine(var='stat_mean', mad=True)
        # Mask values where the variance is NaN
        supercube.mask |= np.isnan(supercube._var)

        fname = os.path.join(self.output_dir, 'SUPERFLAT.fits')
        supercube.write(fname, savemask='nan')

        superim = supercube.mean(axis=0)
        fname = os.path.join(self.output_dir, 'SUPERFLAT_IMAGE.fits')
        superim.write(fname, savemask='nan')

        # 3. Subtract superflat
        self.logger.info('Applying superflat to %s', flist[0])
        expcube = Cube(flist[0])
        assert expcube.shape == supercube.shape

        # Do nothing for masked values
        supercube._data[supercube.mask] = 0
        supercube._var[supercube.mask] = 0
        expcube -= supercube

        fname = os.path.join(self.output_dir, 'DATACUBE_FINAL.fits')
        expcube.write(fname, savemask='nan')
        fname = os.path.join(self.output_dir, 'IMAGE_FOV_0001.fits')
        im = expcube.mean(axis=0)
        im.write(fname, savemask='nan')
