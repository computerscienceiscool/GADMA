from . import Engine
from ..models import DemographicModel, StructureDemographicModel, Epoch, Split
from ..utils import DynamicVariable
from .. import SFSDataHolder
import os
import numpy as np

class DadiOrMomentsEngine(Engine):
    """
    Engine for using :py:mod:`dadi` for demographic inference.

    Citation of :py:mod:`dadi`:

    Gutenkunst RN, Hernandez RD, Williamson SH, Bustamante CD (2009)
    Inferring the Joint Demographic History of Multiple Populations
    from Multidimensional SNP Frequency Data. PLoS Genet 5(10): e1000695.
    https://doi.org/10.1371/journal.pgen.1000695
    """

    id = 'dadi_or_moments'  #:
    base_module = None  #:
    supported_models = [DemographicModel, StructureDemographicModel]  #:
    supported_data = [SFSDataHolder]  #:
    inner_data_type = None  # base_module.Spectrum  #:

    @classmethod
    def read_data(cls, data_holder):
        """
        Reads SFS data from `data_holder`.

        Could read two types of data:

            * :py:mod:`dadi` SFS data type
            * :py:mod:`dadi` SNP data type

        Check :py:mod:`dadi` manual for additional information.

        :param data_holder: holder of the data.
        :type data_holder: :class:`SFSDataHolder`
        """
        if data_holder.__class__ not in cls.supported_data:
            raise ValueError(f"Data class {data_holder.__class__.__name__}"
                             f" is not supported by {cls.id} engine.\nThe "
                             f"supported classes are: {cls.supported_data}"
                             f" and {cls.inner_data_type}")
        data = read_dadi_data(cls.base_module, data_holder)
        return data

    def _get_key(self, x, grid_sizes):
        var2value = self.model.var2value(x)
        key = tuple(var2value[var] for var in self.model.variables)
        if isinstance(grid_sizes, float):
            return (key, grid_sizes)
        return (key, tuple(grid_sizes))

    def get_theta(self, values, grid_sizes):
        key = self._get_key(values, grid_sizes)
        if key not in self.saved_add_info:
            Warning("Additional evaluation for theta. Nothing to worry if seldom.")
            self.evaluate(values, grid_sizes)
        return self.saved_add_info[key]

    def get_N_ancestral(self, theta):
        if self.model.theta0 is not None:
            theta0 = self.model.theta0
        elif (self.model.mu is not None and self.data_holder is not None and
                self.data_holder.sequence_length is not None):
            theta0 = 4 * self.model.mu * self.data_holder.sequence_length
        else:
            return None
        return theta / theta0

    def evaluate(self, values, grid_sizes):
        """
        Simulates SFS from values and evaluate log likelihood between
        simulated SFS and observed SFS.
        """
        if self.data is None or self.model is None:
            raise ValueError("Please set data and model for the engine or"
                             " use set_and_evaluate function instead.")
        model = self.simulate(values, self.data.sample_sizes, grid_sizes)
        ll_model = self.base_module.Inference.ll_multinom(model, self.data)
        # Save theta
        theta = self.base_module.Inference.optimal_sfs_scaling(model, self.data)
#        print(values, ll_model, theta)
        key = self._get_key(values, grid_sizes)
        self.saved_add_info[key] = theta
        return ll_model


# Those functions are common for dadi and moments engines.
def _check_missing_population_labels(sfs, default_pop_labels=None):
    """
    Check that SFS has population labels. If not then make them default.

    : param sfs: site frequency spectrum to check
    : type sfs: dadi.Spectrum (or analogue)
    : param default_population_labels: if pop. labels are missing use this values.
    """
    if sfs.pop_ids is None:
        if default_pop_labels is not None:
            Warning("Spectrum file %s is in an old format - without"
                    " population labels, so they will be taken from"
                    " corresponding parameter: %s."
                    % (filename, ', '.join(population_labels)))
            sfs.pop_ids = population_labels
        else:
            sfs.pop_ids = ['Pop %d' % (i+1) for i in range(sfs.ndim)]
    return sfs


def _new_population_labels(sfs, new_labels):
    """
    Assign new order of population labels of SFS.

    : param sfs: site frequency spectrum to change its labels
    : type sfs: dadi.Spectrum (or analogue)
    : param new_labels: new population labels
    """
    if new_labels is None:
        return sfs
    if sfs.pop_ids != new_labels:
        # Create a permutation of axis
        d = {x: i for i, x in enumerate(sfs.pop_ids)}
        try:
            d = [d[x] for x in new_labels]
        except:  # NOQA
            raise ValueError("Wrong Population labels parameter, population"
                             " labels are: " + ', '.join(sfs.pop_ids))
        # Rotate axis
        sfs = np.transpose(sfs, d)
        sfs.pop_ids = new_labels
    return sfs


def _project(sfs, new_size):
    """
    Project SFS to new sample size.

    : param sfs: site frequency spectrum to change its size
    : type sfs: dadi.Spectrum (or analogue)
    : param new_size: new sample size
    : type new_size: np.ndarray
    """
    if new_size is None:
        return sfs
    if not list(new_size) == list(sfs.sample_sizes):
        try:
            sfs = sfs.project(new_size)
        except Exception as e:
            raise ValueError("Wrong projections of SFS: " + str(e))
    return sfs


def _get_default_from_snp_format(filename):
    """
    Returns population labels, the possibility of outgroup and approximation
    of size from file of dadi's SNP format.
    """
    with open(filename) as f:
        line = f.readline()
        while line.startswith('#'):
            line = f.readline()
        # Read the header of file
        info = line.split()
        if (len(info) - 6) % 2 != 0:
            raise ValueError("Cannot calculate number of populations in"
                             " dadi's SNP input file. Maybe it's wrong?")
        n_pop = int((len(info) - 6) / 2)
        pop_ids = info[3: 3 + n_pop]
        # Find approximate size and check existence of the outgroup
        has_outgroup = True
        appr_size = np.zeros(n_pop, dtype=int)
        for line in f:
            info = line.split()
            if info[1][1].lower() not in ['a', 't', 'c', 'g']:
                has_outgroup = False
            for num in range(n_pop):
                cur_size = int(info[3 + num]) + int(info[4 + n_pop + num])
                if cur_size > appr_size[num]:
                    appr_size[num] = cur_size
    return pop_ids, has_outgroup, appr_size


def _change_outgroup(sfs, new_outgroup):
    """
    Change polarization of the data. If data does not have outgroup
    then error.
    """
    if new_outgroup is not None:
        if new_outgroup and sfs.folded:
            raise ValueError("Data does not have outgroup.")
        if not new_outgroup:
            sfs.fold()
    return sfs


def _read_data_sfs_type(module, data_holder):
    """
    Read filename of dadi's sfs format. Check dadi's manual for further
    information.

    : param module: dadi or moments module (or analogue)
    : param data_holder: object holding the data.
    : type  data_holder: gadma.data.DataHolder
    """
    sfs = module.Spectrum.from_file(data_holder.filename)
    ns = np.array(sfs.shape) - 1

    sfs = _check_missing_population_labels(sfs, data_holder.population_labels)
    sfs = _new_population_labels(sfs, data_holder.population_labels)
    sfs = _project(sfs, data_holder.projections)
    sfs = _change_outgroup(sfs, data_holder.outgroup)
    return sfs


def _read_data_snp_type(module, data_holder):
    """
    Read filename of dadi's SNP format. Check dadi's manual for further
    information.

    : param module: dadi or moments module (or analogue)
    : param data_holder: object holding the data.
    : type  data_holder: gadma.data.DataHolder
    """
    try:
        dd = module.Misc.make_data_dict(data_holder.filename)
    except Exception as e:
        raise SyntaxError("Construction of data_dict failed: " + str(e))
    population_labels, has_outgroup, size = _get_default_from_snp_format(
        data_holder.filename)
    if data_holder.projections is not None:
        size = data_holder.projections
    if data_holder.population_labels is not None:
        population_labels = data_holder.pop_labels
    sfs = module.Spectrum.from_data_dict(dd, population_labels, size, has_outgroup)
    sfs = _change_outgroup(sfs, data_holder.outgroup)
    return sfs


def read_dadi_data(module, data_holder):
    """
    Read file in one of dadi's formats.

    :param module: dadi or moments module (or analogue)
    :param data_holder: object holding the data.
    :type  data_holder: gadma.data.DataHolder

    :returns: ('sfs'/'snp', data)
    :rtype: (str, :class:`dadi.Spectrum`)
    """
    _, ext = os.path.splitext(data_holder.filename)
    if ext == '.fs' or ext == '.sfs':
        return _read_data_sfs_type(module, data_holder)
    elif ext == '.txt':
        return _read_data_snp_type(module, data_holder)
    else:
        # Try to guess
        try:
            return _read_data_sfs_type(module, data_holder)
        except:  # NOQA
            try:
                return _read_data_snp_type(module, data_holder)
            except:  # NOQA
                raise SyntaxError("Data filename extension is neither .fs"
                                  " (.sfs) or .txt. Attempts to guess the"
                                  " file type failed.\nTo get the error "
                                  "message, please, change the extension.")