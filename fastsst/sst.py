# -*- coding: utf-8 -*-
import numpy as np
from numba import jit
from sklearn.preprocessing import MinMaxScaler
from .util.linear_algebra import power_method,lanczos,eig_tridiag

class SingularSpectrumTransformation():
    def __init__(self,win_length,n_components=3,order=None,lag=None,\
        use_lanczos=True,rank_lanczos=None,eps=1e-3):
        """Change point detection with Singular Spectrum Transformation

        Parameters
        ----------
        win_length : int
            window length of Hankel matrix.
        n_components : int
            specify how many rank of Hankel matrix will be taken.
        order : int
            number of columns of Hankel matrix.
        lag : int
            interval between history Hankel matrix and test Hankel matrix.
        use_lanczos : boolean
            if true, lanczos method will be used, which makes faster.
        rank_lanczos : int
            the rank which will be used for lanczos method.
            for the detail of lanczos method, see [1].
        eps : float
            specify how much noise will be added to initial vector for power method.
            for the detail, see [2].

        References
        ----------
        [1]: Tsuyoshi Ide et al., Change-Point Detection using Krylov Subspace Learning
        [2]: Tsuyoshi Ide, Speeding up Change-Point Detection using Matrix Compression (Japanse)

        """
        self.win_length = win_length
        self.n_components = n_components
        self.order = order
        self.lag = lag
        self.use_lanczos = use_lanczos
        self.rank_lanczos = rank_lanczos
        self.eps = eps

    def score_offline(self,x):
        """calculate anomaly score (offline)

        Parameters
        ----------
        x : 1d numpy array
            input time series data.

        Returns
        -------
        score : 1d array
            change point score.

        """
        if self.order is None:
            # rule of thumb
            self.order = self.win_length
        if self.lag is None:
            # rule of thumb
            self.lag = self.order // 2
        if self.rank_lanczos is None:
            # rule of thumb
            if self.n_components % 2 == 0:
                self.rank_lanczos = 2 * self.n_components
            else:
                self.rank_lanczos = 2 * self.n_components - 1

        assert isinstance(x,np.ndarray), "input array must be numpy array."
        assert x.ndim == 1, "input array dimension must be 1."
        assert isinstance(self.win_length,int), "window length must be int."
        assert isinstance(self.n_components,int), "number of components must be int."
        assert isinstance(self.order,int), "order of partial time series must be int."
        assert isinstance(self.lag,int), "lag between test series and history series must be int."
        assert isinstance(self.rank_lanczos,int), "rank for lanczos must be int."

        # all values should be positive for numerical stabilization
        x_scaled = MinMaxScaler(feature_range=(1,2)).fit_transform(x.reshape(-1,1))[:,0]

        score = _score_offline(x_scaled,self.order,\
            self.win_length,self.lag,self.n_components,self.rank_lanczos,self.eps,
            use_lanczos=self.use_lanczos)

        return score

@jit(nopython=True)
def _score_offline(x,order,win_length,lag,n_components,rank,eps,use_lanczos):
    """core implementation of offline score calculation
    """
    start_idx = win_length + order + lag + 1
    end_idx = x.size + 1

    # initialize vector for power method
    x0 = np.empty(order,dtype=np.float64)
    x0 = np.random.rand(order)
    x0 /= np.linalg.norm(x0)

    score = np.zeros_like(x)
    for t in range(start_idx,end_idx):
        # compute score at each index

        # get Hankel matrix
        X_history = _create_hankel(x,order,
            start = t - win_length - lag,
            end = t - lag
        )
        X_test = _create_hankel(x,order,
            start = t - win_length,
            end = t
        )

        P_history = X_history.T @ X_history
        P_test = X_test.T @ X_test

        if use_lanczos:
            score[t-1],x1 = _sst_lanczos(P_test,P_history,n_components,rank,x0)
            # update initial vector for power method
            x0 = x1 + eps * np.random.rand(x0.size)
            x0 /= np.linalg.norm(x0)
        else:
            score[t-1] = _sst_svd(P_test,P_history,n_components)

    return score

@jit(nopython=True)
def _create_hankel(x,order,start,end):
    """create Hankel matrix

    Parameters
    ----------
    x : full time series
    order : order of Hankel matrix
    start : start index
    end : end index

    Returns
    -------
    2d array [window length, order]

    """
    win_length = end - start
    X = np.empty((win_length,order))
    for i in range(order):
        X[:,i] = x[(start - i):(end - i)]
    return X

@jit(nopython=True)
def _sst_lanczos(P_test,P_history,n_components,rank,x0):
    """run sst algorithm with lanczos method (FELIX-SST algorithm)
    """
    # calculate the first singular vec of test matrix
    u,_,_ = power_method(P_test,x0,n_iter=1)
    T = lanczos(P_history,u,rank)
    val,vec = eig_tridiag(T)
    return 1 - (vec[0,:n_components] ** 2).sum(),u

@jit("f8(f8[:,:],f8[:,:],u1)",nopython=True)
def _sst_svd(P_test,P_history,n_components):
    """run sst algorithm with svd
    """
    U_test,_,_ = np.linalg.svd(P_test,full_matrices=False)
    U_history,_,_ = np.linalg.svd(P_history,full_matrices=False)
    _,s,_ = np.linalg.svd(U_test[:,:n_components].T @ U_history[:,:n_components],\
        full_matrices=False)
    return 1 - s[0]