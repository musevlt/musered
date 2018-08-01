from .recipe import Recipe


class ScienceRecipe(Recipe):
    """Mother class for science recipes."""


class SCIBASIC(ScienceRecipe):

    recipe_name = 'muse_scibasic'
    output_dir = 'scibasic'
    use_illum = True
    env = {'MUSE_PIXTABLE_SAVE_AS_IMAGE': 1}
    default_params = {'saveimage': False}


class STANDARD(ScienceRecipe):

    recipe_name = 'muse_standard'
    DPR_TYPE = 'PIXTABLE_STD'
    output_dir = 'STD'
    exclude_frames = ('TELLURIC_REGIONS', ) + ScienceRecipe.exclude_frames
    default_params = {'filter': 'white,Johnson_V,Cousins_R,Cousins_I'}


classes = {cls.recipe_name: cls for cls in ScienceRecipe.__subclasses__()}

__all__ = tuple(cls.__name__ for cls in ScienceRecipe.__subclasses__())
