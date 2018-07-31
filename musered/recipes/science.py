from .recipe import Recipe

__all__ = ('SCIBASIC', )


class SCIBASIC(Recipe):

    recipe_name = 'muse_scibasic'
    output_dir = 'scibasic'
    use_illum = True
    env = {'MUSE_PIXTABLE_SAVE_AS_IMAGE': 1}
    default_params = {'saveimage': False}


class STANDARD(Recipe):

    recipe_name = 'muse_standard'
    DPR_TYPE = 'PIXTABLE_STD'
    output_dir = 'STD'
    exclude_frames = ('TELLURIC_REGIONS', ) + Recipe.exclude_frames
    default_params = {'filter': 'white,Johnson_V,Cousins_R,Cousins_I'}


_classes = {cls.recipe_name: cls
            for cls in (SCIBASIC, STANDARD)}


def get_recipe_cls(recipe_name):
    if recipe_name not in _classes:
        raise ValueError(f'invalid recipe_name {recipe_name}')

    return _classes[recipe_name]
