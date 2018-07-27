from .recipe import Recipe

__all__ = ('BIAS', 'DARK', 'FLAT', 'WAVECAL', 'LSF', 'SKYFLAT')


class BIAS(Recipe):

    recipe_name = 'muse_bias'
    DPR_TYPE = 'BIAS'
    n_inputs_min = 3


class DARK(Recipe):

    recipe_name = 'muse_dark'
    DPR_TYPE = 'DARK'
    n_inputs_min = 3


class FLAT(Recipe):

    recipe_name = 'muse_flat'
    DPR_TYPE = 'FLAT,LAMP'
    default_params = {'samples': True}
    n_inputs_min = 3


class WAVECAL(Recipe):

    recipe_name = 'muse_wavecal'
    DPR_TYPE = 'WAVE'
    exclude_frames = ('MASTER_FLAT', ) + Recipe.exclude_frames


class LSF(Recipe):

    recipe_name = 'muse_lsf'
    DPR_TYPE = 'WAVE'


class SKYFLAT(Recipe):

    recipe_name = 'muse_twilight'
    DPR_TYPE = 'FLAT,SKY'
    n_inputs_min = 3
    use_illum = True


_classes = {cls.recipe_name: cls
            for cls in (BIAS, DARK, FLAT, WAVECAL, LSF, SKYFLAT)}


def get_recipe_cls(recipe_name):
    if recipe_name not in _classes:
        raise ValueError(f'invalid recipe_name {recipe_name}')

    return _classes[recipe_name]
