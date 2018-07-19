from ..recipe import Recipe


class BIAS(Recipe):

    recipe_name = 'muse_bias'
    OBJECT = 'BIAS'
    OBJECT_out = 'MASTER_BIAS'
    n_inputs_min = 3

    def _run(self, biaslist, **kwargs):
        results = self._recipe(raw={'BIAS': biaslist}, **kwargs)
        return results


class DARK(Recipe):

    recipe_name = 'muse_dark'
    OBJECT = 'DARK'
    OBJECT_out = 'MASTER_DARK'
    n_inputs_min = 3

    def _run(self, darklist, **kwargs):
        results = self._recipe(raw={'DARK': darklist}, **kwargs)
        return results


class FLAT(Recipe):

    recipe_name = 'muse_flat'
    OBJECT = 'FLAT,LAMP'
    OBJECT_out = 'MASTER_FLAT'
    default_params = {'samples': True}
    n_inputs_min = 3

    def _run(self, flatlist, **kwargs):
        results = self._recipe(raw={'FLAT': flatlist}, **kwargs)
        return results


class WAVECAL(Recipe):

    recipe_name = 'muse_wavecal'
    OBJECT = 'WAVE'
    OBJECT_out = 'WAVECAL_TABLE'
    default_params = {'saveimages': True}
    n_inputs_min = 1

    def _run(self, arclist, **kwargs):
        results = self._recipe(raw={'ARC': arclist}, **kwargs)
        return results


calib_classes = {cls.OBJECT: cls for cls in (BIAS, DARK, FLAT, WAVECAL)}
