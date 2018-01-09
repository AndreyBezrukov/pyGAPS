"""
This module calculates the initial enthalpy of adsorption based on an isotherm.
"""

import warnings

import numpy
import scipy

from ..classes.adsorbate import Adsorbate
from ..graphing.calcgraph import initial_enthalpy_plot
from ..utilities.exceptions import CalculationError
from ..utilities.exceptions import ParameterError


def initial_enthalpy_comp(isotherm, enthalpy_key, branch='ads', verbose=False, **param_guess):
    """
    Calculates an initial enthalpy based on a compound
    method with three separate contributions:

        * A constant contribution
        * An 'active site' decaying exponential contribution
        * A power contribution to model adsorbate-adsorbate interactions

    Parameters
    ----------
    isotherm : PointIsotherm
        Isotherm to use for the calculation.
    enthalpy_key : str
        The column which stores the enthalpy data.
    branch : str
        The isotherm branch to use for the calculation. Default is adsorption branch.
    verbose : bool, optional
        Whether to print out extra information.

    Returns
    -------
    dict
        Dict containing initial enthalpy and fitting parameters.
    """

    # Read data in
    loading = isotherm.loading(branch=branch,
                               loading_unit='mmol',
                               loading_basis='molar')
    loading = loading / max(loading)
    enthalpy = isotherm.other_data(enthalpy_key, branch=branch)

    if enthalpy is None:
        raise ParameterError('Could not find enthalpy column in isotherm')

    # Clean up data
    index = []
    for i, point in enumerate(enthalpy):
        if point < 0 or point > 400:
            index.append(i)
    if len(index) > 0:
        loading = numpy.delete(loading, index)
        enthalpy = numpy.delete(enthalpy, index)

    ##################################
    ##################################
    # First define the parameters

    param_names = ['const', 'preexp', 'exp',
                   'prepowa', 'powa', 'prepowr', 'powr']
    params = {name: numpy.nan for name in param_names}

    # Then the functions
    def constant_term(l):
        return params['const']

    def exponential_term(l):
        return params['preexp'] * numpy.exp(params['exp'] * l)

    def power_term_repulsive(l):
        return params['prepowr'] * l ** params['powr']

    def power_term_attractive(l):
        return params['prepowa'] * l ** params['powa']

    def enthalpy_approx(l):
        return constant_term(l) + exponential_term(l) + power_term_repulsive(l) + power_term_attractive(l)

    def residual_sum_of_squares(params_):
        for i, _ in enumerate(param_names):
            params[param_names[i]] = params_[i]

        return numpy.sum(((enthalpy - enthalpy_approx(loading)) / enthalpy) ** 2)

    ##################################
    ##################################
    # We need to set some limits for the parameters to make sure
    # the solver returns realistic values

    bounds = dict()
    ##################################
    # The constant term

    # We calculate the standard deviation
    enth_avg = numpy.average(enthalpy)
    enth_stdev = numpy.std(enthalpy)

    # The minimum should be at least the enthalpy of liquefaction
    # although it depends on the strength of the interaction with the
    # active site.

    bounds['const_min'] = enth_avg - 2 * enth_stdev
    # We check enthalpy of liquefaction
    adsorbate = Adsorbate.from_list(isotherm.adsorbate)
    try:
        bounds['const_min'] = max(adsorbate.enthalpy_liquefaction(
            isotherm.t_exp), bounds['const_min'])
    except CalculationError as e_info:
        warnings.warn(
            "Could not calculate liquid enthalpy, perhaps in supercritical regime")

    # The maximum constant contribution is taken similar to the minimum
    const_avg = max(enth_avg, bounds['const_min'])
    bounds['const_max'] = const_avg

    ##################################
    # The exponential term

    # The constant term is meant to model the active sites or defects
    # in the material. It is composed of an exponential and
    # preexponential term

    # The contribution should always lead to a decreasing
    # enthalpy of adsorption. Therefore:
    # The exponential term cannot be positive
    bounds['exp_min'] = -numpy.inf
    bounds['exp_max'] = 0

    # The preexponential term cannot be negative
    bounds['preexp_min'] = 0
    # At zero loading, the enthalpy of adsorption is going to
    # be the preexponential factor + the constant factor.
    # Physically, there must be a limit for this interaction
    # even for chemisorption. We set a conservative limit.
    bounds['preexp_max'] = 150

    ##################################
    # The power term

    # The power term is supposed to model the guest-guest interactions
    # with two components: the power and the coefficient
    # The power should be at least 1 (1-1 interactions)
    bounds['powa_min'] = 1
    bounds['powr_min'] = 1
    # We set a realistic upper limit on the number of interactions
    bounds['powa_max'] = 50
    bounds['powr_max'] = 50

    bounds['prepowa_min'] = 0
    bounds['prepowa_max'] = numpy.inf
    bounds['prepowr_min'] = -numpy.inf
    bounds['prepowr_max'] = 0
    # ###############
    # Update with user values
    bounds.update(param_guess)

    # Generate bounds tuple
    bounds_arr = (
        (bounds.get('const_min'), bounds.get('const_max')),
        (bounds.get('preexp_min'), bounds.get('preexp_max')),
        (bounds.get('exp_min'), bounds.get('exp_max')),
        (bounds.get('prepowa_min'), bounds.get('prepowa_max')),
        (bounds.get('powa_min'), bounds.get('powa_max')),
        (bounds.get('prepowr_min'), bounds.get('prepowr_max')),
        (bounds.get('powr_min'), bounds.get('powr_max')),
    )

    if verbose:
        print('Bounds: \n\tconst =', (bounds_arr[0]), ', preexp =', bounds_arr[1],
              ', exp =', bounds_arr[2], ', prepowa =', bounds_arr[3], ', powa =', bounds_arr[4],
              ', prepowr =', bounds_arr[5], ', powr =', bounds_arr[6])

    ##################################
    ##################################
    # Constraints on the parameters
    def maximize_constant(params_):
        return params_[0] - params_[1] * numpy.exp(params_[2] * loading) - params_[3] * loading ** params_[4] - params_[5] * loading ** params_[6]
    constr = ({'type': 'ineq', 'fun': maximize_constant})

    ##################################
    ##################################
    # We will do an optimisation with different starting guesses
    # then check which one fits best

    # Get a value for the departure of the first point:
    dep_first = min(max(enthalpy[0], 0), 150) - const_avg
    dep_last = min(max(enthalpy[-1], 0), 150) - const_avg
    guesses = (
        # Starting from a constant value
        numpy.array([const_avg, 0, 0, 0, 1, 0, 1]),
        # Starting from an adjusted start and end
        numpy.array([const_avg,
                     dep_first, 0,
                     dep_last, 1,
                     dep_last, 1]),
        # Starting from a large exponent and gentle power increase
        numpy.array([const_avg,
                     1.5 * dep_first, -10,
                     0.01, 3,
                     0, 1]),
        # Starting from no exponent and gentle power decrease
        numpy.array([const_avg,
                     0, 0,
                     0, 3,
                     -0.01, 3]),
    )

    options = {
        'disp': verbose,
        'maxiter': 100000,
        'ftol': 1e-8,
    }

    min_fun = numpy.inf
    final_guess = None
    best_fit = None

    for guess in guesses:
        if verbose:
            print('Initial guesses: \n\tconst =', guess[0], ', preexp =', guess[1],
                  ', exp =', guess[2], ', prepowa =', guess[3], ', powa =', guess[4],
                  ', prepowr =', guess[5], ', powr =', guess[6])
        opt_res = scipy.optimize.minimize(residual_sum_of_squares, guess,
                                          bounds=bounds_arr, constraints=constr,
                                          method='SLSQP', options=options)

        if opt_res.fun < min_fun:
            final_guess = opt_res.x
            best_fit = opt_res.fun

    if final_guess is None:
        raise CalculationError(
            "\n\tMinimization of RSS fitting failed with all guesses")
    if verbose:
        print('Final best fit', best_fit)

    for i, _ in enumerate(param_names):
        params[param_names[i]] = final_guess[i]

    initial_enthalpy = enthalpy_approx(0)
    if abs(initial_enthalpy - enthalpy[0]) > 50:
        warnings.warn(
            "Probable offshoot for exponent, reverting to point method")
        initial_enthalpy = initial_enthalpy_point(
            isotherm, enthalpy_key, branch=branch, verbose=verbose).get('initial_enthalpy')

    if verbose:
        print("The initial enthalpy of adsorption is: \n\tE =",
              round(initial_enthalpy, 2))
        print("The constant contribution is \n\t{:.2f}".format(
            params['const']))
        print("The exponential contribution is \n\t{:.2f} * exp({:.2E} * n)".format(
            params['preexp'], params['exp']))
        print("The guest-guest attractive contribution is \n\t{:.2g} * n^{:.2}".format(
            params['prepowa'], params['powa']))
        print("The guest-guest repulsive contribution is \n\t{:.2g} * n^{:.2}".format(
            params['prepowr'], params['powr']))

        x_axis = numpy.linspace(0, 1)
        baseline = constant_term(x_axis)
        extras = (
            (x_axis, [baseline for x in x_axis], 'constant'),
            (x_axis, baseline + exponential_term(x_axis), 'exponential'),
            (x_axis, baseline + power_term_attractive(x_axis), 'power attr'),
            (x_axis, baseline + power_term_repulsive(x_axis), 'power rep'),
        )

        title = ' '.join(
            [isotherm.sample_name, isotherm.sample_batch, isotherm.adsorbate])
        initial_enthalpy_plot(
            loading, enthalpy, enthalpy_approx(loading), title=title, extras=extras)

    params.update({'initial_enthalpy': initial_enthalpy})

    return params


def initial_enthalpy_point(isotherm, enthalpy_key, branch='ads', verbose=False):
    """
    Calculates the initial enthalpy of adsorption by assuming it is the same
    as the first point in the curve.

    Parameters
    ----------
    isotherm : PointIsotherm
        Isotherm to use for the calculation.
    enthalpy_key : str
        The column which stores the enthalpy data.
    branch : str
        The isotherm branch to use for the calculation. Default is adsorption branch.
    verbose : bool, optional
        Whether to print out extra information.

    Returns
    -------
    dict
        Dict containing initial enthalpy and other parameters.
    """

    # Read data in
    enthalpy = isotherm.other_data(enthalpy_key, branch=branch)

    if enthalpy is None:
        raise ParameterError('Could not find enthalpy column in isotherm')

    initial_enthalpy = enthalpy[0]

    if verbose:
        print("The initial enthalpy of adsorption is: \n\tE =",
              round(initial_enthalpy, 2))

        loading = isotherm.loading(branch=branch,
                                   loading_unit='mmol',
                                   loading_basis='molar')
        title = ' '.join(
            [isotherm.sample_name, isotherm.sample_batch, isotherm.adsorbate])
        initial_enthalpy_plot(
            loading, enthalpy, [initial_enthalpy for i in loading], title=title)

    return {'initial_enthalpy': initial_enthalpy}
