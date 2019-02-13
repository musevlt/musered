import logging
import numpy as np
import os
import pathlib
import platform
import shutil

from astropy.io import fits
from astropy.table import Table
from glob import glob
from joblib import Parallel, delayed
from mpdaf.obj import Cube, CubeList
from os.path import join
from tempfile import TemporaryDirectory

from ..masking import mask_sources
from ..utils import make_band_images
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
        'cache_pixtables': False,
        'method': 'sigclip',
        'scipost': {'filter': 'white'},
        'filter': 'white,Johnson_V,Cousins_R,Cousins_I',
    }

    @property
    def calib_frames(self):
        # We suppose that most of the scipost steps were already run (flux
        # calibration, sky subtraction, autocalib), so we exclude all these
        # frames to speedup the frame association.
        exclude = ('RAMAN_LINES', 'STD_RESPONSE', 'STD_TELLURIC',
                   'LSF_PROFILE', 'SKY_CONTINUUM')
        return [f for f in SCIPOST(verbose=False).calib_frames
                if f not in exclude]

    def get_pixtables(self, name, path):
        """Return pixtables path, after optionally caching them."""
        cachedir = self.param.get('cache_pixtables')
        if isinstance(cachedir, dict):
            # get cachedir specific to a given hostname
            cachedir = cachedir.get(platform.node())

        if cachedir:
            cachedir = pathlib.Path(cachedir) / name
            if not cachedir.exists():
                cachedir.mkdir(parents=True)
                for f in glob(f"{path}/PIXTABLE_REDUCED*.fits"):
                    self.logger.debug('copy %s to %s', f, cachedir)
                    shutil.copy(f, cachedir)
            return glob(f"{cachedir}/PIXTABLE_REDUCED*.fits")
        else:
            return glob(f"{path}/PIXTABLE_REDUCED*.fits")

    def _run(self, flist, *args, exposures=None, name=None, **kwargs):
        hdr = fits.getheader(flist[0])
        ra, dec = hdr['RA'], hdr['DEC']
        info = self.logger.info

        # 1. Run scipost for all exposures used to build the superflat
        run = exposures[exposures['name'] == name]['run'][0]
        exps = exposures[(exposures['run'] == run) &
                         (exposures['name'] != name)]
        nexps = len(exps)
        info('Found %d exposures for run %s', nexps, run)

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

        # Prepare scipost recipe and args, and remove OFFSET_LIST as offsets
        # are applied manually above
        recipe = SCIPOST(log_dir=self.log_dir)
        recipe_kw = {key: kwargs[key] for key in self.calib_frames
                     if key in kwargs and key != 'OFFSET_LIST'}

        cubelist = []
        self.raw['SUPERFLAT_EXPS'] = []

        for i, exp in enumerate(exps, start=1):
            outdir = join(self.output_dir, 'cubes', exp['name'])
            outname = f'{outdir}/DATACUBE_FINAL.fits'
            if os.path.exists(outname):
                info('%d/%d : %s already processed', i, nexps, exp['name'])
            else:
                info('%d/%d : %s processing', i, nexps, exp['name'])
                explist = self.get_pixtables(exp['name'], exp['path'])
                self.raw['SUPERFLAT_EXPS'] += explist
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
            info(f'Combining cubes with method {method}')
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
        im.write(join(outdir, 'IMAGE_WHITE.fits'), savemask='nan')

        if self.param['filter']:
            make_band_images(expcube, 'IMAGE_FOV_{filt}.fits',
                             self.param['filter'])


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
