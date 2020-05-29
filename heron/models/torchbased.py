"""
Models which use the GPyTorch GPR package as their backbone.
"""

import math
from functools import reduce
import operator

import pkg_resources

import numpy as np

import torch
import gpytorch
from gpytorch.kernels import RBFKernel
from gpytorch.constraints import GreaterThan, LessThan

from matplotlib import pyplot as plt

from . import Model
from .gw import BBHSurrogate, HofTSurrogate

DATA_PATH = pkg_resources.resource_filename('heron', 'models/data/')

class HeronCUDA(Model, BBHSurrogate, HofTSurrogate):
    """
    A GPR BBH waveform model which is capable of using CUDA resources.
    """

    time_factor = 100
    strain_input_factor = 1e21


    def __init__(self):
        """
        Construct a CUDA-based waveform model with pyTorch
        """
        
        # super(HeronCUDA, self).__init__()
        self.model, self.likelihood = self.build()
        self.x_dimensions = 8
        self.time_factor = 1
        self.strain_input_factor = 1e21
        #
        self.eval()

    def eval(self):
        """
        Prepare the model to be evaluated.
        """
        self.model.eval()
        self.likelihood.eval()

    def _process_inputs(self, times, p):
        times *= self.time_factor
        #p['mass ratio'] *= 100 #= np.log(p['mass ratio']) * 100
        p = {k: 100*v for k, v in p.items()}
        return times, p

    def build(self):
        """
        Right now this isn't need by this method
        """

        def prod(iterable):
            return reduce(operator.mul, iterable)

        mass_kernel = RBFKernel(active_dims=1,
                                lengthscale_constraint=GreaterThan(10.))
        time_kernel = RBFKernel(active_dims=0,
                                lengthscale_constraint=GreaterThan(0.1))
        spin_kernels = [RBFKernel(active_dims=dimension,
                                  lengthscale_constraint=GreaterThan(7))
                        for dimension in range(2, 8)]

        class ExactGPModel(gpytorch.models.ExactGP):
            """
            Use the GpyTorch Exact GP
            """
            def __init__(self, train_x, train_y, likelihood):
                super(ExactGPModel, self).__init__(train_x, train_y, likelihood)
                self.mean_module = gpytorch.means.ZeroMean()
                self.covar_module = gpytorch.kernels.ScaleKernel(
                    time_kernel*mass_kernel*prod(spin_kernels),
                    lengthscale_constraint=gpytorch.constraints.LessThan(0.01)
                )

            def forward(self, x):
                mean_x = self.mean_module(x)
                covar_x = self.covar_module(x)
                return gpytorch.distributions.MultivariateNormal(mean_x, covar_x)

        data = np.genfromtxt(pkg_resources.resource_filename('heron',
                                                             'models/data/gt-M60-F1024.dat'))

        training_x = torch.tensor(data[:, 0:-2]*100).float().cuda()
        training_y = torch.tensor(data[:, -2]*1e21).float().cuda()

        likelihood = gpytorch.likelihoods.GaussianLikelihood(noise_constraint=LessThan(10))
        model = ExactGPModel(training_x, training_y, likelihood)
        state_vector = pkg_resources.resource_filename('heron', 'models/data/gt-gpytorch.pth')

        model = model.cuda()
        likelihood = likelihood.cuda()

        model.load_state_dict(torch.load(state_vector))

        return model, likelihood

    def mean(self, times, p, covariance=False):
        """
        Provide the mean waveform and its variance. 
        Optionally include the covariance.

        Pararameters
        -------------
        times : ndarray
           The times at which the model should be evaluated.
        p : dict 
           A dictionary of locations in parameter space where the model should be evaluated.
        covariance : bool, optional
           A flag to determine if the whole covariance matrix should be returned.

        Returns
        -------
        mean : torch.tensor
           The mean waveform
        var : torch.tensor
            The variance of the waveform
        cov : torch.tensor, optional
            The covariance matrix of the waveform. 
            Only returned if covariance was True.
        """

        covariance_flag = covariance
        times_b = times.copy()
        points = self._generate_eval_matrix(p, times_b)
        points = torch.tensor(points).float().cuda()
        with torch.no_grad(), gpytorch.settings.fast_pred_var():
            f_preds = self.model(points)

        mean = f_preds.mean/self.strain_input_factor
        var = f_preds.variance.detach().double()/(self.strain_input_factor**2)
        covariance = f_preds.covariance_matrix.detach().double()/(self.strain_input_factor**2)

        if covariance_flag:
            return mean, var, covariance
        else:
            return mean, var

    def distribution(self, times, p, samples=100):
        """
        Return a number of sample waveforms from the GPR distribution.
        """
        times_b = times.copy()
        points = self._generate_eval_matrix(p, times_b)
        points = torch.tensor(points).float().cuda()
        with torch.no_grad(), gpytorch.settings.fast_pred_var():
            f_preds = self.model(points)
            y_preds = self.likelihood(f_preds)

        return y_preds.sample_n(samples)/self.strain_input_factor

    def frequency_domain_waveform(self, p, times=np.linspace(-2, 2, 1000)):
        """
        Return the frequency domain waveform.
        """
        mean, _, cov = self.mean(times, p, covariance=True)

        strain_f = mean.rfft(1)
        cov_f = cov.rfft(2)

        uncert_f = torch.stack([torch.diag(cov_f[:, :, 0]), torch.diag(cov_f[:, :, 1])]).T

        return strain_f, uncert_f

    def time_domain_waveform(self, p, times=np.linspace(-2, 2, 1000)):
        """
        Return the timedomain waveform.
        """
        mean, var = self.mean(times, p)

        return mean, var

    def plot_td(self, parameters, times=np.linspace(-2, 2, 1000), f=None):
        """
        Plot the timedomain waveform.
        """
        if not f:
            f, ax = plt.subplots(1, 1, dpi=300)
        else:
            ax = f.axes[0]

        mean, var = self.time_domain_waveform(parameters, times)
        mean = mean.cpu().numpy()
        var = var.cpu().numpy()

        ax.plot(times, mean)
        ax.fill_between(times, mean+np.abs(var), mean-np.abs(var), alpha=0.1)

        return f
