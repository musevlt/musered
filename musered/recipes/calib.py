from .recipe import Recipe


class CalibRecipe(Recipe):
    """Mother class for calibration recipes."""


class BIAS(CalibRecipe):

    recipe_name = 'muse_bias'
    DPR_TYPE = 'BIAS'
    n_inputs_min = 3
    n_inputs_rec = 11


class DARK(CalibRecipe):

    recipe_name = 'muse_dark'
    DPR_TYPE = 'DARK'
    n_inputs_min = 3


class FLAT(CalibRecipe):

    recipe_name = 'muse_flat'
    DPR_TYPE = 'FLAT,LAMP'
    default_params = {'samples': True}
    n_inputs_min = 3
    n_inputs_rec = 11


class WAVECAL(CalibRecipe):

    recipe_name = 'muse_wavecal'
    DPR_TYPE = 'WAVE'
    n_inputs_rec = 15
    exclude_frames = ('MASTER_FLAT', ) + CalibRecipe.exclude_frames


class LSF(CalibRecipe):

    recipe_name = 'muse_lsf'
    DPR_TYPE = 'WAVE'


class SKYFLAT(CalibRecipe):

    recipe_name = 'muse_twilight'
    DPR_TYPE = 'FLAT,SKY'
    n_inputs_min = 3
    n_inputs_rec = 8
    use_illum = True


classes = {cls.recipe_name: cls for cls in CalibRecipe.__subclasses__()}

__all__ = tuple(cls.__name__ for cls in CalibRecipe.__subclasses__())
