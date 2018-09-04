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


class SCIPOST(ScienceRecipe):

    recipe_name = 'muse_scipost'
    DPR_TYPE = 'PIXTABLE_OBJECT'
    output_dir = 'scipost'
    # exclude optional frames
    exclude_frames = (('SKY_CONTINUUM', 'OUTPUT_WCS', 'OFFSET_LIST',
                       'SKY_MASK') + ScienceRecipe.exclude_frames)
    # Save the V,R,I images
    default_params = {'filter': 'white,Johnson_V,Cousins_R,Cousins_I'}


class EXPALIGN(ScienceRecipe):

    recipe_name = 'muse_exp_align'
    DPR_TYPE = 'IMAGE_FOV'
    output_dir = 'exp_align'
    n_inputs_min = 2


class EXPCOMBINE(ScienceRecipe):

    recipe_name = 'muse_exp_combine'
    DPR_TYPE = 'PIXTABLE_REDUCED'
    output_dir = 'exp_combine'
    n_inputs_min = 2
    # Save the V,R,I images
    default_params = {'filter': 'white,Johnson_V,Cousins_R,Cousins_I'}


sci_classes = {cls.recipe_name: cls for cls in ScienceRecipe.__subclasses__()}

__all__ = tuple(cls.__name__ for cls in ScienceRecipe.__subclasses__())