from .recipe import Recipe

__all__ = ('SCIBASIC', )


class SCIBASIC(Recipe):

    recipe_name = 'muse_scibasic'
    DPR_TYPE = 'OBJECT'
    env = {'MUSE_PIXTABLE_SAVE_AS_IMAGE': 1}


_classes = {cls.recipe_name: cls
            for cls in (SCIBASIC, )}


def get_recipe_cls(recipe_name):
    if recipe_name not in _classes:
        raise ValueError(f'invalid recipe_name {recipe_name}')

    return _classes[recipe_name]
