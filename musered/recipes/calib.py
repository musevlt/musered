from ..recipe import Recipe


class BIAS(Recipe):

    recipe_name = 'muse_bias'
    # outdir = BIASDIR

    def _run(self, biaslist, badpix_table=None):
        if len(biaslist) < 3:
            raise ValueError('Error need at least 3 exposures')

        if badpix_table is not None:
            self._recipe.calib.BADPIX_TABLE = badpix_table

        results = self._recipe(raw={'BIAS': biaslist})

        return results


class DARK(Recipe):

    recipe_name = 'muse_dark'
    # outdir = DARKDIR

    def _run(self, darklist, master_bias, badpix_table=None):
        if len(darklist) < 3:
            raise ValueError('Error need at least 3 exposures')

        self._recipe.calib.MASTER_BIAS = master_bias
        if badpix_table is not None:
            self._recipe.calib.BADPIX_TABLE = badpix_table

        results = self._recipe(raw={'DARK': darklist})

        return results


class FLAT(Recipe):

    recipe_name = 'muse_flat'
    # outdir = FLATDIR
    default_params = {'samples': True}

    def _run(self, flatlist, master_bias, master_dark=None, badpix_table=None):
        if len(flatlist) < 3:
            raise ValueError('Error need at least 3 exposures')

        self._recipe.calib.MASTER_BIAS = master_bias
        if master_dark is not None:
            self._recipe.calib.MASTER_DARK = master_dark
        if badpix_table is not None:
            self._recipe.calib.BADPIX_TABLE = badpix_table

        results = self._recipe(raw={'FLAT': flatlist})

        return results
