from .recipe import Recipe


class ScienceRecipe(Recipe):
    """Mother class for science recipes."""


class SCIBASIC(ScienceRecipe):

    recipe_name = 'muse_scibasic'
    output_dir = 'scibasic'
    use_illum = True
    # Don't save the pre-processed CCD-based image
    default_params = {'saveimage': False}


class STANDARD(ScienceRecipe):

    recipe_name = 'muse_standard'
    DPR_TYPE = 'PIXTABLE_STD'
    output_dir = 'STD'
    # TELLURIC_REGIONS is not needed, use the DRS default values instead
    exclude_frames = ('TELLURIC_REGIONS', ) + ScienceRecipe.exclude_frames
    # Save the V,R,I images
    default_params = {'filter': 'white,Johnson_V,Cousins_R,Cousins_I'}


sci_classes = {cls.recipe_name: cls for cls in ScienceRecipe.__subclasses__()}

__all__ = tuple(cls.__name__ for cls in ScienceRecipe.__subclasses__())
