"""
Module contains 'classical' methods of calculating a pore size distribution for
pores in the micropore range (<2 nm). These are derived from the HK models.
"""

from typing import List
from typing import Mapping

import numpy
import scipy.constants as const
import scipy.optimize as opt

from ..core.adsorbate import Adsorbate
from ..graphing.calc_graphs import psd_plot
from ..utilities.exceptions import CalculationError
from ..utilities.exceptions import ParameterError
from .models_hk import HK_KEYS
from .models_hk import get_hk_model

_MICRO_PSD_MODELS = ['HK', 'HK-CY', 'RY', 'RY-CY']
_PORE_GEOMETRIES = ['slit', 'cylinder', 'sphere']


def psd_microporous(
    isotherm,
    psd_model='HK',
    pore_geometry='slit',
    branch='ads',
    material_model='Carbon(HK)',
    adsorbate_model=None,
    p_limits=None,
    verbose=False
):
    """
    Calculate the microporous size distribution using a Horvath-Kawazoe type model.

    Parameters
    ----------
    isotherm : Isotherm
        Isotherm for which the pore size distribution will be calculated.
    psd_model : str
        The pore size distribution model to use.
    pore_geometry : str
        The geometry of the adsorbent pores.
    branch : {'ads', 'des'}, optional
        Branch of the isotherm to use. It defaults to adsorption.
    material_model : str or dict
        The material model to use for PSD, It defaults to 'Carbon(HK)', the original
        Horvath-Kawazoe carbon parameters.
    adsorbate_model : dict or `None`
        The adsorbate properties to use for PSD, If null, properties are
        automatically searched from the Adsorbent.
    p_limits : [float, float]
        Pressure range in which to calculate PSD, defaults to [0, 0.2].
    verbose : bool
        Prints out extra information on the calculation and graphs the results.

    Returns
    -------
    dict
        A dictionary with the pore widths and the pore distributions, of the form:

            - ``pore_widths`` (array) : the widths of the pores
            - ``pore_distribution`` (array) : contribution of each pore width to the
              overall pore distribution

    Notes
    -----
    Calculates the pore size distribution using a 'classical' model which
    attempts to describe the adsorption in a pore of specific width w at a
    relative pressure p/p0 as a single function :math:`p/p0 = f(w)`. This
    function uses properties of the adsorbent and adsorbate as a way of
    determining the pore size distribution.

    Currently, the methods provided are:

        - the HK, or Horvath-Kawazoe method
        - the HK-CY, or Cheng-Yang nonlinear (Langmuir) corrected HK method
        - the RY, or Rege-Yang HK-derived method
        - the RY-CY, or Cheng-Yang nonlinear (Langmuir) corrected RY method

    A common mantra of data processing is: "garbage in = garbage out". Only use
    methods when you are aware of their limitations and shortcomings.

    See Also
    --------
    pygaps.characterisation.psd_microporous.psd_horvath_kawazoe : low level HK (Horvath-Kawazoe) method
    pygaps.characterisation.psd_microporous.psd_hk_cheng_yang : low level HK-CY (Cheng-Yang) method
    pygaps.characterisation.psd_microporous.psd_hk_rege_yang : low level HK-RY (Rege-Yang) method

    """
    # Function parameter checks
    if psd_model is None:
        raise ParameterError(
            "Specify a model to generate the pore size"
            " distribution e.g. psd_model=\"HK\""
        )
    if psd_model not in _MICRO_PSD_MODELS:
        raise ParameterError(
            f"Model {psd_model} not an option for psd. "
            f"Available models are {_MICRO_PSD_MODELS}"
        )
    if pore_geometry not in _PORE_GEOMETRIES:
        raise ParameterError(
            f"Geometry {pore_geometry} not an option for pore size distribution. "
            f"Available geometries are {_PORE_GEOMETRIES}"
        )
    if branch not in ['ads', 'des']:
        raise ParameterError(
            f"Branch '{branch}' not an option for PSD.",
            "Select either 'ads' or 'des'"
        )

    # Get adsorbate properties
    if adsorbate_model is None:
        if not isinstance(isotherm.adsorbate, Adsorbate):
            raise ParameterError(
                "Isotherm adsorbate is not known, cannot calculate PSD."
                "Either use a recognised adsorbate (i.e. nitrogen) or "
                "pass a dictionary with your adsorbate parameters."
            )
        adsorbate_model = {
            'molecular_diameter':
            isotherm.adsorbate.get_prop('molecular_diameter'),
            'polarizability':
            isotherm.adsorbate.get_prop('polarizability'),
            'magnetic_susceptibility':
            isotherm.adsorbate.get_prop('magnetic_susceptibility'),
            'surface_density':
            isotherm.adsorbate.get_prop('surface_density'),
            'liquid_density':
            isotherm.adsorbate.liquid_density(isotherm.temperature),
            'adsorbate_molar_mass':
            isotherm.adsorbate.molar_mass(),
        }

    # Get adsorbent properties
    material_properties = get_hk_model(material_model)

    # Read data in
    loading = isotherm.loading(
        branch=branch, loading_basis='molar', loading_unit='mmol'
    )
    pressure = isotherm.pressure(branch=branch, pressure_mode='relative')
    if loading is None:
        raise ParameterError(
            "The isotherm does not have the required branch "
            "for this calculation"
        )
    # If on an desorption branch, data will be reversed
    if branch == 'des':
        loading = loading[::-1]
        pressure = pressure[::-1]

    # Determine the limits
    if not p_limits:
        p_limits = (None, 0.2)
    minimum = 0
    maximum = len(pressure)
    if p_limits[0]:
        minimum = numpy.searchsorted(pressure, p_limits[0])
    if p_limits[1]:
        maximum = numpy.searchsorted(pressure, p_limits[1])
    if maximum - minimum < 3:  # (for 3 point minimum)
        raise CalculationError(
            "The isotherm does not have enough points (at least 3) "
            "in the selected region."
        )
    pressure = pressure[minimum:maximum]
    loading = loading[minimum:maximum]

    # Call specified pore size distribution function
    if psd_model in ['HK', 'HK-CY']:
        pore_widths, pore_dist, pore_vol_cum = psd_horvath_kawazoe(
            pressure,
            loading,
            isotherm.temperature,
            pore_geometry,
            adsorbate_model,
            material_properties,
            use_cy=False if psd_model == 'HK' else True,
        )
    elif psd_model in ['RY', 'RY-CY']:
        pore_widths, pore_dist, pore_vol_cum = psd_horvath_kawazoe_ry(
            pressure,
            loading,
            isotherm.temperature,
            pore_geometry,
            adsorbate_model,
            material_properties,
            use_cy=False if psd_model == 'RY' else True,
        )

    if verbose:
        psd_plot(
            pore_widths,
            pore_dist,
            pore_vol_cum=pore_vol_cum,
            log=False,
            right=5,
            method=psd_model
        )

    return {
        'pore_widths': pore_widths,
        'pore_distribution': pore_dist,
        'pore_volume_cumulative': pore_vol_cum,
    }


def psd_horvath_kawazoe(
    pressure: List[float],
    loading: List[float],
    temperature: float,
    pore_geometry: str,
    adsorbate_properties: Mapping[str, float],
    material_properties: Mapping[str, float],
    use_cy: bool = False,
):
    r"""
    Calculate the pore size distribution using the Horvath-Kawazoe method.

    Parameters
    ----------
    loading : array
        Adsorbed amount in mmol/g.
    pressure : array
        Relative pressure.
    temperature : float
        Temperature of the experiment, in K.
    pore_geometry : str
        The geometry of the pore, eg. 'sphere', 'cylinder' or 'slit'.
    adsorbate_properties : dict
        Properties for the adsorbate in the form of::

            adsorbate_properties = dict(
                'molecular_diameter': 0,           # nm
                'polarizability': 0,               # nm3
                'magnetic_susceptibility': 0,      # nm3
                'surface_density': 0,              # molecules/m2
                'liquid_density': 0,               # g/cm3
                'adsorbate_molar_mass': 0,         # g/mol
            )

    material_properties : dict
        Properties for the adsorbate in the same form
        as 'adsorbate_properties'. A list of common models
        can be found in .characterisation.models_hk.
    use_cy : bool:
        Whether to use the Cheng-Yang nonlinear term.

    Returns
    -------
    pore widths : array
        The widths of the pores.
    pore_dist : array
        The distributions for each width.
    pore_vol_cum : array
        Cumulative pore volume.

    Notes
    -----

    *Description*

    The H-K method [#]_ attempts to describe the adsorption within pores by
    calculation of the average potential energy for a pore. The method starts by
    assuming the following relationship between the two phases:

    .. math::

        R_g T \ln(\frac{p}{p_0}) = U_0 + P_a

    Here :math:`U_0` is the potential function describing the surface to
    adsorbent interactions and :math:`P_a` is the potential function describing
    the adsorbate- adsorbate interactions. This equation is derived from the
    equation of the free energy of adsorption at constant temperature where
    adsorption entropy term :math:`T \Delta S^{tr}(w/w_{\infty})` is assumed to
    be negligible.

------------------------------------------------------------------------------------------------
    A cylindrical model

    ..[#] A. Saito and H. C. Foley, Curvature and Parametric Sensitivity in
    Models for Adsorption in Micropores, AIChE J., 37, 429, 1991.

------------------------------------------------------------------------------------------------
    The equation assumes that adsorption follows Henry's law. A correction was
    proposed by Cheng and Yang [#]_ which incorporate a Langmuir type behaviour
    of adsorbed molecules.

    ..[#] L. S. Cheng and R. T. Yang, ‘‘Improved Horvath-Kawazoe Equations
    Including Spherical Pore Models for Calculating Micropore Size
    Distribution,’’ Chem. Eng. Sci., 49, 2599, 1994.

------------------------------------------------------------------------------


    If a Lennard-Jones-type potential function describes the interactions
    between the adsorbate molecules and the adsorbent molecules then the two
    contributions to the total potential can be replaced by the extended
    function. The resulting equation becomes:

    .. math::

        RT\ln(p/p_0) =   & N_A\frac{n_a A_a + n_A A_A}{2 \sigma^{4}(l-d)} \\
                        & \times \int_{d/_2}^{1-d/_2}
                            \Big[
                            - \Big(\frac{\sigma}{r}\Big)^{4}
                            + \Big(\frac{\sigma}{r}\Big)^{10}
                            - \Big(\frac{\sigma}{l-r}\Big)^{4}
                            + \Big(\frac{\sigma}{l-r}\Big)^{4}
                            \Big] \mathrm{d}x

    Where:

    * :math:`R` -- gas constant
    * :math:`T` -- temperature
    * :math:`l` -- width of pore
    * :math:`d` -- defined as :math:`d=d_a+d_A` the sum of the diameters of the adsorbate and
      adsorbent molecules
    * :math:`N_A` -- Avogadro's number
    * :math:`n_a` -- number of molecules of adsorbent
    * :math:`A_a` -- the Lennard-Jones potential constant of the adsorbent molecule defined as

        .. math::
            A_a = \frac{6mc^2\alpha_a\alpha_A}{\alpha_a/\varkappa_a + \alpha_A/\varkappa_A}

    * :math:`A_A` -- the Lennard-Jones potential constant of the adsorbate molecule defined as

        .. math::
            A_a = \frac{3 m_e c_l ^2\alpha_A\varkappa_A}{2}

    * :math:`m_e` -- mass of an electron
    * :math:`c_l` -- speed of light in vacuum
    * :math:`\alpha_a` -- polarizability of the adsorbate molecule
    * :math:`\alpha_A` -- polarizability of the adsorbent molecule
    * :math:`\varkappa_a` -- magnetic susceptibility of the adsorbate molecule
    * :math:`\varkappa_A` -- magnetic susceptibility of the adsorbent molecule


    *Limitations*

    The assumptions made by using the H-K method are:

        - It does not have a description of capillary condensation. This means
          that the pore size distribution can only be considered accurate up to
          a maximum of 5 nm.

        - Each pore is uniform and of infinite length. Materials with varying
          pore shapes or highly interconnected networks may not give realistic
          results.

        - The surface is made up of a single layer of atoms. Furthermore, since
          the HK method is reliant on knowing the properties of the surface
          atoms as well as the adsorbent molecules the material should ideally
          be homogenous.

        - Only dispersive forces are accounted for. If the adsorbate-adsorbent
          interactions have other contributions, the Lennard-Jones potential
          function will not be an accurate description of pore environment.

    References
    ----------
    .. [#] G. Horvath and K. Kawazoe, Method for Calculation of Effective Pore
    Size Distribution in Molecular Sieve Carbon, J. Chem. Eng. Japan, 16, 470 1983.

    .. [#] S. U. Rege and R. T. Yang, Corrected Horváth-Kawazoe equations for
    pore-size distribution, AIChE Journal, vol. 46, no. 4, pp. 734–750, Apr.
    2000.


    """
    # Parameter checks
    missing = [x for x in material_properties if x not in HK_KEYS]
    if missing:
        raise ParameterError(
            f"Adsorbent properties dictionary is missing parameters: {missing}."
        )

    missing = [
        x for x in adsorbate_properties if x not in list(HK_KEYS.keys()) +
        ['liquid_density', 'adsorbate_molar_mass']
    ]
    if missing:
        raise ParameterError(
            f"Adsorbate properties dictionary is missing parameters: {missing}."
        )

    # ensure numpy arrays
    pressure = numpy.asarray(pressure)
    loading = numpy.asarray(loading)

    # Constants unpacking and calculation
    d_ads = adsorbate_properties['molecular_diameter']
    d_mat = material_properties['molecular_diameter']
    n_ads = adsorbate_properties['surface_density']
    n_mat = material_properties['surface_density']

    a_ads, a_mat = _dispersion_from_dict(
        adsorbate_properties, material_properties
    )  # dispersion constants

    d_eff = (d_ads + d_mat) / 2  # effective diameter
    N_over_RT = _N_over_RT(temperature)

    ###################################################################
    if pore_geometry == 'slit':

        sigma = 0.8583742 * d_eff  # (2/5)**(1/6)*d_eff, internuclear distance at 0 energy
        sigma_p4_o3 = sigma**4 / 3  # pre-calculated constant
        sigma_p10_o9 = sigma**10 / 9  # pre-calculated constant

        const_coeff = (
            N_over_RT * (n_ads * a_ads + n_mat * a_mat) / (sigma * 1e-9)**4
        )  # sigma must be in SI here

        const_term = (
            sigma_p10_o9 / (d_eff**9) - sigma_p4_o3 / (d_eff**3)
        )  # nm

        def potential(l_pore):
            return (
                const_coeff / (l_pore - 2 * d_eff) *
                ((sigma_p4_o3 / (l_pore - d_eff)**3) -
                 (sigma_p10_o9 / (l_pore - d_eff)**9) + const_term)
            )

        if use_cy:
            pore_widths = _solve_hk_cy(pressure, loading, potential, 2 * d_eff)
        else:
            pore_widths = _solve_hk(pressure, potential, 2 * d_eff)

        # width = distance between infinite slabs - 2 * surface molecule radius (=d_mat)
        pore_widths = numpy.asarray(pore_widths) - d_mat

    ###################################################################
    elif pore_geometry == 'cylinder':

        const_coeff = 0.75 * const.pi * N_over_RT * \
            (n_ads * a_ads + n_mat * a_mat) / (d_eff * 1e-9)**4  # d_eff must be in SI

        def potential(l_pore):
            # 0.65625 is (21 / 32), constant

            a_k, b_k = 1, 1
            d_over_r = d_eff / l_pore  # dimensionless
            k_sum = 0.65625 * d_over_r**10 - d_over_r**4  # first value at K=0

            # 30 * pore radius ensures that layer convergence is achieved
            for k in range(1, int(l_pore * 30)):
                a_k = ((-4.5 - k) / k)**2 * a_k
                b_k = ((-1.5 - k) / k)**2 * b_k
                k_sum = k_sum + (
                    (1 / (k + 1) * (1 - d_over_r)**(2 * k)) *
                    (0.65625 * a_k * (d_over_r)**10 - b_k * (d_over_r)**4)
                )

            return const_coeff * k_sum

        if use_cy:
            pore_widths = _solve_hk_cy(pressure, loading, potential, d_eff)
        else:
            pore_widths = _solve_hk(pressure, potential, d_eff)

        # width = 2 * cylinder radius - 2 * surface molecule radius (=d_mat)
        pore_widths = 2 * numpy.asarray(pore_widths) - d_mat

    ###################################################################
    elif pore_geometry == 'sphere':

        p_12 = a_mat / (4 * (d_eff * 1e-9)**6)  # ads-surface potential depth
        p_22 = a_ads / (4 * (d_ads * 1e-9)**6)  # ads-ads potential depth

        def potential(l_pore):

            l_minus_d = l_pore - d_eff
            d_over_l = d_eff / l_pore

            n_1 = 4 * const.pi * (l_pore * 1e-9)**2 * n_mat
            n_2 = 4 * const.pi * (l_minus_d * 1e-9)**2 * n_ads

            def t_term(x):
                return (1 + (-1)**x * l_minus_d / l_pore)**(-x) -\
                    (1 - (-1)**x * l_minus_d / l_pore)**(-x)

            return N_over_RT * (
                6 * (n_1 * p_12 + n_2 * p_22) * (l_pore / l_minus_d)**3
            ) * (
                -(d_over_l**6) * (1 / 12 * t_term(3) + 1 / 8 * t_term(2)) +
                (d_over_l**12) * (1 / 90 * t_term(9) + 1 / 80 * t_term(8))
            )

        if use_cy:
            pore_widths = _solve_hk_cy(pressure, loading, potential, d_eff)
        else:
            pore_widths = _solve_hk(pressure, potential, d_eff)

        # width = 2 * sphere radius - 2 * surface molecule radius (=d_mat)
        pore_widths = 2 * numpy.asarray(pore_widths) - d_mat

    # finally calculate pore distribution
    liquid_density = adsorbate_properties['liquid_density']
    adsorbate_molar_mass = adsorbate_properties['adsorbate_molar_mass']

    avg_pore_widths = numpy.add(pore_widths[:-1], pore_widths[1:]) / 2  # nm
    volume_adsorbed = loading * adsorbate_molar_mass / liquid_density / 1000  # cm3/g
    pore_dist = numpy.diff(volume_adsorbed) / numpy.diff(pore_widths)

    # TODO do not cut, look into values close to pore width
    out = (1e-3 < pore_dist) & (pore_dist < 1e3)  # cut infinite values

    return avg_pore_widths[out], pore_dist[out], volume_adsorbed[1:][out]


def psd_horvath_kawazoe_ry(
    pressure: List[float],
    loading: List[float],
    temperature: float,
    pore_geometry: str,
    adsorbate_properties: Mapping[str, float],
    material_properties: Mapping[str, float],
    use_cy: bool = False,
):
    # Parameter checks
    missing = [x for x in material_properties if x not in HK_KEYS]
    if missing:
        raise ParameterError(
            f"Adsorbent properties dictionary is missing parameters: {missing}."
        )

    missing = [
        x for x in adsorbate_properties if x not in list(HK_KEYS.keys()) +
        ['liquid_density', 'adsorbate_molar_mass']
    ]
    if missing:
        raise ParameterError(
            f"Adsorbate properties dictionary is missing parameters: {missing}."
        )

    # ensure numpy arrays
    pressure = numpy.asarray(pressure)
    loading = numpy.asarray(loading)

    # Constants unpacking and calculation
    d_ads = adsorbate_properties['molecular_diameter']
    d_mat = material_properties['molecular_diameter']
    n_ads = adsorbate_properties['surface_density']
    n_mat = material_properties['surface_density']

    a_ads, a_mat = _dispersion_from_dict(
        adsorbate_properties, material_properties
    )  # dispersion constants

    d_eff = (d_ads + d_mat) / 2  # effective diameter
    N_over_RT = _N_over_RT(temperature)

    ###################################################################
    if pore_geometry == 'slit':

        sigma_mat = 0.858374219 * d_eff  # (2/5)**(1/6) * d_eff,
        sigma_ads = 0.858374219 * d_ads  # (2/5)**(1/6) * d_ads,
        s_over_da = sigma_ads / d_ads  # pre-calculated constant
        s_over_d0 = sigma_mat / d_eff  # pre-calculated constant

        # potential with adsorbate bulk
        def potential_adsorbate():
            return (
                n_ads * a_ads / (2 * (sigma_ads * 1e-9)**4) *
                (-s_over_da**4 + s_over_da**10)
            )

        # potential with surface
        def potential_surface():
            return (
                n_mat * a_mat / (2 * (sigma_mat * 1e-9)**4) *
                (-s_over_d0**4 + s_over_d0**10)
            ) + potential_adsorbate()

        # potential with two interacting surfaces
        def potential_twosurface(l_pore):
            return n_mat * a_mat / (2 * (sigma_mat * 1e-9)**4) * (
                -s_over_d0**4 + s_over_d0**10 - (sigma_mat /
                                                 (l_pore - d_eff))**4 +
                (sigma_mat / (l_pore - d_eff))**10
            )

        def average_potential(n_layer):
            return ((
                2 * potential_surface() +
                (n_layer - 2) * 2 * potential_adsorbate()  # 2 * is correct
            ) / n_layer)

        def potential(l_pore):
            n_layer = (l_pore - d_mat) / d_ads
            if n_layer < 2:
                return N_over_RT * potential_twosurface(l_pore)
            else:
                return N_over_RT * average_potential(n_layer)

        if use_cy:
            pore_widths = _solve_hk_cy(pressure, loading, potential, 2 * d_eff)
        else:
            pore_widths = _solve_hk(pressure, potential, 2 * d_eff)

        # width = distance between infinite slabs - 2 * surface molecule radius (=d_mat)
        pore_widths = numpy.asarray(pore_widths) - d_mat

    ###################################################################
    elif pore_geometry == 'cylinder':
        # 0.65625 is (21 / 32), constant

        def k_sum(l_pore, ratio, n):
            x_k = 1
            k_sum = 1

            for k in range(1, int(l_pore * 30)):
                k_sum = k_sum + (x_k * ratio**(2 * k))
                x_k = ((-n - k) / k)**2 * x_k

            return k_sum

        # potential with surface (first layer)
        def potential_general(l_pore, d_x, n_x, a_x, r1, r2):
            return (
                0.75 * const.pi * n_x * a_x / ((d_x * 1e-9)**4) * (
                    0.65625 * r1**10 * k_sum(l_pore, r2, 4.5) -
                    r1**4 * k_sum(l_pore, r2, 1.5)
                )
            )

        def potential(l_pore):
            n_layers = int((l_pore - d_mat) / d_ads - 0.5) + 1
            layer_populations = []
            layer_potentials = []

            for layer in range(1, n_layers):
                width = 2 * (l_pore - d_eff - (layer - 1) * d_ads)
                if d_ads < width:
                    layer_population = const.pi / numpy.sin(d_mat / width
                                                            )**(-1)
                else:
                    layer_population = 1

                if layer == 1:
                    r1 = d_eff / l_pore
                    r2 = (l_pore - d_eff) / l_pore
                    layer_potential = potential_general(
                        l_pore, d_eff, n_mat, a_mat, r1, r2
                    )
                else:
                    r1 = d_ads / (l_pore - d_eff - (layer - 2) * d_ads)
                    r2 = ((l_pore - d_eff - (layer - 1) * d_ads) /
                          (l_pore - d_eff - (layer - 2) * d_ads))
                    layer_potential = potential_general(
                        l_pore, d_ads, n_ads, a_ads, r1, r2
                    )

                layer_populations.append(layer_population)
                layer_potentials.append(layer_potential)

            layer_molecules = numpy.asarray(layer_population)
            layer_potentials = numpy.asarray(
                layer_potentials
            )  # should be one smaller

            return (
                N_over_RT * numpy.sum(layer_molecules * layer_potentials) /
                numpy.sum(layer_molecules)
            )

        if use_cy:
            pore_widths = _solve_hk_cy(pressure, loading, potential, d_eff)
        else:
            pore_widths = _solve_hk(pressure, potential, d_eff)

        # width = 2 * cylinder radius - 2 * surface molecule radius (=d_mat)
        pore_widths = 2 * numpy.asarray(pore_widths) - d_mat

    ###################################################################
    elif pore_geometry == 'sphere':

        p_12 = a_mat / (4 * (d_eff * 1e-9)**6)  # ads-surface potential depth
        p_22 = a_ads / (4 * (d_ads * 1e-9)**6)  # ads-ads potential depth

        def potential_general(n_m, p_xx, r1, r2):
            """General layer potential in a spherical regime."""
            return (
                2 * n_m * p_xx *
                ((-r1**6 / (4 * r2) * ((1 - r2)**(-4) - (1 + r2)**(-4))) +
                 (r1**12 / (10 * r2) * ((1 - r2)**(-10) - (1 + r2)**(-10))))
            )

        def potential(l_pore):
            n_layers = int((l_pore - d_mat) / d_ads - 0.5) + 1
            layer_populations = []
            layer_potentials = []

            for layer in range(1, n_layers):

                if layer == 1:  # potential with surface (first layer)
                    layer_population = 4 * const.pi * l_pore**2 * n_mat
                    r1 = d_eff / l_pore
                    r2 = (l_pore - d_eff) / l_pore
                    layer_potential = potential_general(
                        layer_population, p_12, r1, r2
                    )

                else:  # inter-adsorbate potential (subsequent layers).
                    layer_population = 4 * const.pi * (
                        l_pore - d_eff - (layer - 1) * d_ads
                    )**2 * n_ads
                    r1 = d_ads / (l_pore - d_eff - (layer - 2) * d_ads)
                    r2 = ((l_pore - d_ads - (layer - 1) * d_ads) /
                          (l_pore - d_ads - (layer - 2) * d_ads))
                    layer_potential = potential_general(
                        layer_populations[-1], p_22, r1, r2
                    )

                layer_populations.append(layer_population)
                layer_potentials.append(layer_potential)

            layer_molecules = numpy.asarray(layer_population)
            layer_potentials = numpy.asarray(
                layer_potentials
            )  # should be one smaller

            return (
                N_over_RT * numpy.sum(layer_molecules * layer_potentials) /
                numpy.sum(layer_molecules)
            )

        if use_cy:
            pore_widths = _solve_hk_cy(pressure, loading, potential, d_eff)
        else:
            pore_widths = _solve_hk(pressure, potential, d_eff)

        # width = 2 * sphere radius - 2 * surface molecule radius (=d_mat)
        pore_widths = 2 * numpy.asarray(pore_widths) - d_mat

    # finally calculate pore distribution
    liquid_density = adsorbate_properties['liquid_density']
    adsorbate_molar_mass = adsorbate_properties['adsorbate_molar_mass']

    avg_pore_widths = numpy.add(pore_widths[:-1], pore_widths[1:]) / 2  # nm
    volume_adsorbed = loading * adsorbate_molar_mass / liquid_density / 1000  # cm3/g
    pore_dist = numpy.diff(volume_adsorbed) / numpy.diff(pore_widths)

    return avg_pore_widths, pore_dist, volume_adsorbed[1:]


def _solve_hk(pressure, hk_fun, bound):
    """
    I personally found that simple Brent minimization
    gives good results. There may be other, more efficient
    algorithms, like conjugate gradient, but speed is a moot point
    as long as average total runtime is <50 ms.
    The minimisation runs with bounds of effective diameter < x < 100.
    Maximum determinable pore size is limited at 2.5 nm anyway.
    """

    p_w = []

    for p_point in pressure:

        def fun(l_pore):
            return (numpy.exp(hk_fun(l_pore)) - p_point)**2

        res = opt.minimize_scalar(fun, method='bounded', bounds=(bound, 50))
        p_w.append(res.x)

    return p_w


def _solve_hk_cy(pressure, loading, hk_fun, bound):
    """
    In this case, the SF correction factor is subtracted
    from the original function.
    """

    p_w = []
    coverage = loading / loading[-1]

    for p_point, c_point in zip(pressure, coverage):

        def fun(l_pore):
            sf_corr = 1 + 1 / c_point * numpy.log(1 - c_point)
            return (numpy.exp(hk_fun(l_pore) - sf_corr) - p_point)**2

        res = opt.minimize_scalar(fun, method='bounded', bounds=(bound, 50))
        p_w.append(res.x)

    return p_w


def _dispersion_from_dict(ads_dict, mat_dict):

    p_ads = ads_dict['polarizability'] * 1e-27  # to m3
    p_mat = mat_dict['polarizability'] * 1e-27  # to m3
    m_ads = ads_dict['magnetic_susceptibility'] * 1e-27  # to m3
    m_mat = mat_dict['magnetic_susceptibility'] * 1e-27  # to m3

    return (
        _kirkwood_muller_dispersion_ads(p_ads, m_ads),
        _kirkwood_muller_dispersion_mat(p_mat, m_mat, p_ads, m_ads),
    )


def _kirkwood_muller_dispersion_ads(p_ads, m_ads):
    """Calculate the dispersion constant for the adsorbate.

    p and m stand for polarizability and magnetic susceptibility
    """
    return (
        1.5 * const.electron_mass * const.speed_of_light**2 * p_ads * m_ads
    )


def _kirkwood_muller_dispersion_mat(p_mat, m_mat, p_ads, m_ads):
    """Calculate the dispersion constant for the material.

    p and m stand for polarizability and magnetic susceptibility
    """
    return (
        6 * const.electron_mass * const.speed_of_light**2 * p_ads * p_mat /
        (p_ads / m_ads + p_mat / m_mat)
    )


def _N_over_RT(temp):
    """Calculate (N_a / RT)."""
    return (const.Avogadro / const.gas_constant / temp)
