from .recipe import Recipe


class CalibRecipe(Recipe):
    """Mother class for calibration recipes."""


class BIAS(CalibRecipe):

    recipe_name = 'muse_bias'
    DPR_TYPE = 'BIAS'
    n_inputs_min = 3
    n_inputs_rec = 11
    QC_keywords = {
        'MASTER_BIAS': ['QC_BIAS_MASTER_NBADPIX', 'QC_BIAS_MASTER_NSATURATED']
    }


class DARK(CalibRecipe):

    recipe_name = 'muse_dark'
    DPR_TYPE = 'DARK'
    n_inputs_min = 3


class FLAT(CalibRecipe):

    recipe_name = 'muse_flat'
    DPR_TYPE = 'FLAT,LAMP'
    # save the TRACE_SAMPLES files
    default_params = {'samples': True}
    n_inputs_min = 3
    n_inputs_rec = 11
    QC_keywords = {
        'MASTER_FLAT': ['QC_FLAT_MASTER_NSATURATED', 'QC_FLAT_MASTER_MEAN',
                        'QC_FLAT_MASTER_STDEV', 'QC_FLAT_MASTER_INTFLUX'],
        'TRACE_TABLE': ['QC_TRACE_WIDTHS_MEAN', 'QC_TRACE_WIDTHS_STDEV',
                        'QC_TRACE_WIDTHS_MIN', 'QC_TRACE_WIDTHS_MAX',
                        'QC_TRACE_GAPS_MEAN', 'QC_TRACE_GAPS_STDEV',
                        'QC_TRACE_GAPS_MIN', 'QC_TRACE_GAPS_MAX']
    }


class WAVECAL(CalibRecipe):

    recipe_name = 'muse_wavecal'
    DPR_TYPE = 'WAVE'
    n_inputs_rec = 15
    # Don't use MASTER_FLAT
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


calib_classes = {cls.recipe_name: cls for cls in CalibRecipe.__subclasses__()}

__all__ = tuple(cls.__name__ for cls in CalibRecipe.__subclasses__())
