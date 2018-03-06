from scipy import stats
from scipy.special import ndtri

class Prior(object):
    """
    A prior probability distribution.
    """
    pass

class Normal(Prior):
    """
    A normal prior probability distribution.
    """
    
    def __init__(self, mean, std):
        self.mean = mean
        self.std = std
        distro = stats.norm(self.mean, self.std)
        
    def logp(self, x):
        return distro.logpdf(x)

    def transform(self, x):
        """
        Transform from unit normalisation to this prior.

        Parameters
        ----------
        x : float
           The position in the normalised hyperparameter space
        """
        
        return self.mean + self.srd * ndtri(x)
