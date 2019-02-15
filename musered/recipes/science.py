from .recipe import Recipe


class ScienceRecipe(Recipe):
    """Mother class for science recipes."""


class SCIBASIC(ScienceRecipe):
    """muse_scibasic recipe."""

    recipe_name = 'muse_scibasic'
    output_dir = 'scibasic'
    use_illum = True
    # Don't save the pre-processed CCD-based image
    default_params = {'saveimage': False, 'merge': True}


class STANDARD(ScienceRecipe):
    """muse_standard recipe."""

    recipe_name = 'muse_standard'
    DPR_TYPE = 'PIXTABLE_STD'
    output_dir = 'STD'
    # TELLURIC_REGIONS is not needed, use the DRS default values instead
    exclude_frames = ('TELLURIC_REGIONS', )
    # Save the V,R,I images
    default_params = {'filter': 'white,Johnson_V,Cousins_R,Cousins_I'}


class SCIPOST(ScienceRecipe):
    """muse_scipost recipe."""

    recipe_name = 'muse_scipost'
    DPR_TYPE = 'PIXTABLE_OBJECT'
    output_dir = 'scipost'
    exclude_frames = ('SKY_CONTINUUM', )
    # Save the V,R,I images
    default_params = {'filter': 'white,Johnson_V,Cousins_R,Cousins_I'}


class MAKECUBE(ScienceRecipe):
    """muse_scipost_make_cube recipe."""

    # The muse_scipost_make_cube recipe from the DRS miss some options
    # (OFFSET_LIST), so instead we use muse_scipost, which skips the steps that
    # have already been done. And to avoid warnings, we set default options to
    # disable skysub, raman, etc.
    recipe_name = 'muse_scipost_make_cube'
    recipe_name_drs = 'muse_scipost'
    DPR_TYPE = 'PIXTABLE_REDUCED'
    output_dir = 'scipost_cube'
    # exclude optional frames
    # Save the V,R,I images
    default_params = {'filter': 'white,Johnson_V,Cousins_R,Cousins_I',
                      'save': 'cube', 'skymethod': 'none'}

    @property
    def calib_frames(self):
        # Override calibration frames from scipost to avoid loading unwanted
        # calib. Here we just want to produce a cube.
        return ['FILTER_LIST', 'OUTPUT_WCS', 'OFFSET_LIST', 'ASTROMETRY_WCS']


class EXPALIGN(ScienceRecipe):
    """muse_exp_align recipe."""

    recipe_name = 'muse_exp_align'
    DPR_TYPE = 'IMAGE_FOV'
    output_dir = 'exp_align'
    n_inputs_min = 2


class EXPCOMBINE(ScienceRecipe):
    """muse_exp_combine recipe."""

    recipe_name = 'muse_exp_combine'
    DPR_TYPE = 'PIXTABLE_REDUCED'
    output_dir = 'exp_combine'
    n_inputs_min = 2
    # Save the V,R,I images
    default_params = {'filter': 'white,Johnson_V,Cousins_R,Cousins_I'}
