import moments
import numpy as np

import importlib.util

spec = importlib.util.spec_from_file_location('module', '/mnt/tank/scratch/enoskova/bayes/demographic_inference_data/4_DivMig_11_Sim/demographic_model.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
model_func = module.model_func


data = moments.Spectrum.from_file('/mnt/tank/scratch/enoskova/bayes/demographic_inference_data/4_DivMig_11_Sim/fs_data.fs')
data.pop_ids = ['Pop 1', 'Pop 2', 'Pop 3', 'Pop 4']
ns = data.sample_sizes

p0 = [1.3746898700166281, 1.1261062427166615, 0.8145277043844908, 0.4073395157238986, 0.1630790981145643, 0.2626223850084712, 2.1724528683132713, 0.2447799418525694, 0.13791784325936093, 0.129908171672426, 0.031264801945540655]
model = model_func(p0, ns)
ll_model = moments.Inference.ll_multinom(model, data)
print('Model log likelihood (LL(model, data)): {0}'.format(ll_model))

theta = moments.Inference.optimal_sfs_scaling(model, data)
print('Optimal value of theta: {0}'.format(theta))

# As no theta0 or mut. rate + seq. length are not set
theta0 = 1.0
Nanc = int(theta / theta0)
print('Size of ancestral population: {0}'.format(Nanc))


plot_ns = [4 for _ in ns]  # small sizes for fast drawing
gen_mod = moments.ModelPlot.generate_model(model_func,
                                           p0, plot_ns)
moments.ModelPlot.plot_model(gen_mod,
                             save_file='model_from_GADMA.png',
                             fig_title='Demographic model from GADMA',
                             draw_scale=False,
                             pop_labels=['Pop 1', 'Pop 2', 'Pop 3', 'Pop 4'],
                             nref=None,
                             gen_time=1.0,
                             gen_time_units='generations',
                             reverse_timeline=True)