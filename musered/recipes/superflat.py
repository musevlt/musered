import logging
import numpy as np
import os

from astropy.io import fits
from astropy.table import Table
from glob import glob
from joblib import Parallel, delayed
from mpdaf.obj import Cube, CubeList
from os.path import join
from tempfile import TemporaryDirectory

from ..masking import mask_sources
from .recipe import PythonRecipe
from .science import SCIPOST


class SUPERFLAT(PythonRecipe):

    recipe_name = 'superflat'
    DPR_TYPE = 'DATACUBE_FINAL'
    output_dir = 'superflat'
    output_frames = ['DATACUBE_FINAL', 'IMAGE_FOV', 'SUPERFLAT']
    version = '0.1'
    # Save the V,R,I images
    default_params = {
        'method': 'sigclip',
        'scipost': {'filter': 'white,Johnson_V,Cousins_R,Cousins_I'}
    }

    @property
    def calib_frames(self):
        frames = SCIPOST().calib_frames
        if 'SKY_CONTINUUM' in frames:
            frames.remove('SKY_CONTINUUM')
        return frames

    def _run(self, flist, *args, exposures=None, name=None, **kwargs):
        hdr = fits.getheader(flist[0])
        ra, dec = hdr['RA'], hdr['DEC']

        # 1. Run scipost for all exposures used to build the superflat
        run = exposures[exposures['name'] == name]['run'][0]
        exps = exposures[(exposures['run'] == run) &
                         (exposures['name'] != name)]

        # Fix the RA/DEC/DROT values for all exposures to the values of the
        # reference exp. Take into account the offset of the exposure, as we
        # need the superflat to be aligned with the exposure. The offset is
        # applied them directly to the RA/DEC values, otherwise the DRS checks
        # the exposure name.
        # if 'OFFSET_LIST' in kwargs:
        #     offsets = Table.read(kwargs['OFFSET_LIST'])
        #     offsets = offsets[offsets['DATE_OBS'] == hdr['DATE-OBS']]
        #     ra -= offsets['RA_OFFSET'][0]
        #     dec -= offsets['DEC_OFFSET'][0]

        os.environ['MUSE_SUPERFLAT_POS'] = ','.join(
            map(str, (ra, dec, hdr['ESO INS DROT POSANG'])))

        recipe = SCIPOST()
        recipe_kw = {key: kwargs[key] for key in self.calib_frames
                     if key in kwargs}

        cubelist = []
        for exp in exps:
            outdir = join(self.output_dir, 'cubes', exp['name'])
            outname = f'{outdir}/DATACUBE_FINAL.fits'
            if os.path.exists(outname):
                self.logger.info('%s already processed', exp['name'])
            else:
                self.logger.info('processing %s', exp['name'])
                explist = glob(f"{exp['path']}/PIXTABLE_REDUCED*.fits")
                recipe.run(explist, output_dir=outdir,
                           params=self.param['scipost'], **recipe_kw)
            cubelist.append(outname)

        # 2. Mask sources and combine exposures to obtain the superflat
        prefix = f"superflat.{exp['name']}"
        with TemporaryDirectory(dir=self.temp_dir, prefix=prefix) as tmpdir:
            cubes_masked = [join(tmpdir, *cubef.split(os.sep)[-2:])
                            for cubef in cubelist]
            Parallel(n_jobs=8)(delayed(mask_cube)(cubef, outf)
                               for cubef, outf in zip(cubelist, cubes_masked))

            method = self.param['method']
            self.logger.info(f'Combining cubes with method {method}')
            cubes = CubeList(cubes_masked)
            if method == 'median':
                supercube, expmap, stat = cubes.median()
            elif method == 'sigclip':
                supercube, expmap, stat = cubes.combine(var='propagate',
                                                        mad=True)
                # Mask values where the variance is NaN
                supercube.mask |= np.isnan(supercube._var)
            else:
                raise ValueError(f'unknown method {method}')

        superim = supercube.mean(axis=0)
        expim = expmap.mean(axis=0)
        outdir = self.output_dir
        supercube.write(join(outdir, 'DATACUBE_SUPERFLAT.fits'),
                        savemask='nan')
        expmap.write(join(outdir, 'DATACUBE_EXPMAP.fits.gz'), savemask='nan')
        expim.write(join(outdir, 'IMAGE_EXPMAP.fits'), savemask='nan')
        stat.write(join(outdir, 'STATPIX.fits'), overwrite=True)
        superim.write(join(outdir, 'IMAGE_SUPERFLAT.fits'), savemask='nan')

        # 3. Subtract superflat
        self.logger.info('Applying superflat to %s', flist[0])
        expcube = Cube(flist[0])
        assert expcube.shape == supercube.shape

        # Do nothing for masked values
        mask = supercube.mask.copy()
        supercube.data[mask] = 0
        if supercube.var is not None:
            supercube.var[mask] = 0
        expcube -= supercube
        im = expcube.mean(axis=0)

        expcube.write(join(outdir, 'DATACUBE_FINAL.fits'), savemask='nan')
        im.write(join(outdir, 'IMAGE_FOV_0001.fits'), savemask='nan')


def mask_cube(cubef, outf):
    logger = logging.getLogger(__name__)
    logger.debug('Masking %s', cubef)
    cubedir = os.path.dirname(cubef)
    maskf = join(cubedir, 'MASK_SOURCES.fits')
    mask = mask_sources(join(cubedir, 'IMAGE_FOV_0001.fits'), sigma=5.,
                        iterations=2, opening_iterations=1)
    mask.write(maskf, savemask='none')
    cube = Cube(cubef)
    cube.mask |= mask._data.astype(bool)
    os.makedirs(os.path.dirname(outf), exist_ok=True)
    cube.write(outf, savemask='nan')
