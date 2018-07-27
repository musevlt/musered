from .recipe import Recipe

__all__ = ('BIAS', 'DARK', 'FLAT', 'WAVECAL', 'LSF', 'SKYFLAT')


class BIAS(Recipe):

    recipe_name = 'muse_bias'
    OBJECT = 'BIAS'
    n_inputs_min = 3


class DARK(Recipe):

    recipe_name = 'muse_dark'
    OBJECT = 'DARK'
    n_inputs_min = 3


class FLAT(Recipe):

    recipe_name = 'muse_flat'
    OBJECT = 'FLAT,LAMP'
    default_params = {'samples': True}
    n_inputs_min = 3


class WAVECAL(Recipe):

    recipe_name = 'muse_wavecal'
    OBJECT = 'WAVE'
    n_inputs_min = 1
    exclude_frames = ('MASTER_FLAT', ) + Recipe.exclude_frames


class LSF(Recipe):

    recipe_name = 'muse_lsf'
    OBJECT = 'WAVE'
    n_inputs_min = 1


class SKYFLAT(Recipe):

    recipe_name = 'muse_twilight'
    OBJECT = 'FLAT,SKY'
    n_inputs_min = 3
    use_illum = True


calib_classes = {cls.recipe_name: cls
                 for cls in (BIAS, DARK, FLAT, WAVECAL, LSF, SKYFLAT)}


def get_calib_cls(recipe_name):
    if recipe_name not in calib_classes:
        raise ValueError(f'invalid recipe_name {recipe_name}')

    return calib_classes[recipe_name]
