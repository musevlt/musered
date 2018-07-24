from ..recipe import Recipe


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
    default_params = {'saveimages': True}
    n_inputs_min = 1


calib_classes = {cls.OBJECT: cls for cls in (BIAS, DARK, FLAT, WAVECAL)}


def get_calib_cls(calib_type):
    if calib_type not in calib_classes:
        raise ValueError(f'invalid calib_type {calib_type}')

    return calib_classes[calib_type]
