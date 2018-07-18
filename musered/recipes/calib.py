from ..recipe import Recipe


class BIAS(Recipe):

    recipe_name = 'muse_bias'
    OBJECT = 'BIAS'
    OBJECT_out = 'MASTER_BIAS'

    def _run(self, biaslist, badpix_table=None, **kwargs):
        if len(biaslist) < 3:
            raise ValueError('Error need at least 3 exposures')

        if badpix_table is not None:
            self._recipe.calib.BADPIX_TABLE = badpix_table

        results = self._recipe(raw={'BIAS': biaslist}, **kwargs)

        return results


class DARK(Recipe):

    recipe_name = 'muse_dark'
    OBJECT = 'DARK'
    OBJECT_out = 'MASTER_DARK'

    def _run(self, darklist, master_bias=None, badpix_table=None, **kwargs):
        if len(darklist) < 3:
            raise ValueError('Error need at least 3 exposures')

        if master_bias is not None:
            self._recipe.calib.MASTER_BIAS = master_bias
        if badpix_table is not None:
            self._recipe.calib.BADPIX_TABLE = badpix_table

        results = self._recipe(raw={'DARK': darklist}, **kwargs)

        return results


class FLAT(Recipe):

    recipe_name = 'muse_flat'
    OBJECT = 'FLAT,LAMP'
    OBJECT_out = 'MASTER_FLAT'
    default_params = {'samples': True}

    def _run(self, flatlist, master_bias=None, master_dark=None,
             badpix_table=None, **kwargs):
        if len(flatlist) < 3:
            raise ValueError('Error need at least 3 exposures')

        if master_bias is not None:
            self._recipe.calib.MASTER_BIAS = master_bias
        if master_dark is not None:
            self._recipe.calib.MASTER_DARK = master_dark
        if badpix_table is not None:
            self._recipe.calib.BADPIX_TABLE = badpix_table

        results = self._recipe(raw={'FLAT': flatlist}, **kwargs)

        return results


calib_classes = {cls.OBJECT: cls for cls in (BIAS, DARK, FLAT)}
