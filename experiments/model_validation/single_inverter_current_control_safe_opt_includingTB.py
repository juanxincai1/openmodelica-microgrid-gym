#####################################
# Experiment : Single inverter supplying current to an short circuit via a LR filter
# Controller: PI current controller gain parameters are optimized by SafeOpt
# a) FMU by OpenModelica and SafeOpt algorithm to find optimal controller parameters
# b) connecting via ssh to a testbench to perform real-world measurement


import logging
import os
from functools import partial
from itertools import tee

import GPy
import gym
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from experiments.model_validation.env.physical_testbench import TestbenchEnv
from experiments.model_validation.env.rewards import Reward
from experiments.model_validation.env.stochastic_components import Load
from experiments.model_validation.execution.monte_carlo_runner import MonteCarloRunner
from experiments.model_validation.execution.runner_hardware import RunnerHardware
from openmodelica_microgrid_gym.agents import SafeOptAgent
from openmodelica_microgrid_gym.agents.util import MutableFloat, MutableParams
from openmodelica_microgrid_gym.aux_ctl import PI_params, MultiPhaseDQCurrentSourcingController
from openmodelica_microgrid_gym.env import PlotTmpl
from openmodelica_microgrid_gym.env.plotmanager import PlotManager
from openmodelica_microgrid_gym.net import Network
from openmodelica_microgrid_gym.util import FullHistory

# Plotting params
params = {'backend': 'ps',
          'text.latex.preamble': [r'\usepackage{gensymb}'
                                  r'\usepackage{amsmath,amssymb,mathtools}'
                                  r'\newcommand{\mlutil}{\ensuremath{\operatorname{ml-util}}}'
                                  r'\newcommand{\mlacc}{\ensuremath{\operatorname{ml-acc}}}'],
          'axes.labelsize': 8,  # fontsize for x and y labels (was 10)
          'axes.titlesize': 8,
          'font.size': 8,  # was 10
          'legend.fontsize': 8,  # was 10
          'xtick.labelsize': 8,
          'ytick.labelsize': 8,
          'text.usetex': True,
          'figure.figsize': [3.9, 3.1],
          'font.family': 'serif',
          'lines.linewidth': 1
          }
matplotlib.rcParams.update(params)

# Choose which controller parameters should be adjusted by SafeOpt.
# - Kp: 1D example: Only the proportional gain Kp of the PI controller is adjusted
# - Ki: 1D example: Only the integral gain Ki of the PI controller is adjusted
# - Kpi: 2D example: Kp and Ki are adjusted simultaneously

adjust = 'Kpi'

# Check if really only one simulation scenario was selected
if adjust not in {'Kp', 'Ki', 'Kpi'}:
    raise ValueError("Please set 'adjust' to one of the following values: 'Kp', 'Ki', 'Kpi'")

include_simulate = True
show_plots = True
balanced_load = True
do_measurement = False
save_results = False

# Files saves results and  resulting plots to the folder saves_VI_control_safeopt in the current directory
current_directory = os.getcwd()
save_folder = os.path.join(current_directory, r'../1Test')
os.makedirs(save_folder, exist_ok=True)

np.random.seed(1)

# Simulation definitions
net = Network.load('../../net/net_single-inv-curr_Paper_SC.yaml')
delta_t = 1e-4  # simulation time step size / s
undersample = 1  # undersampling of controller
max_episode_steps = 1000  # number of simulation steps per episode
num_episodes = 1  # number of simulation episodes (i.e. SafeOpt iterations)
n_MC = 1  # number of Monte-Carlo samples for simulation - samples device parameters (e.g. L,R, noise) from
iLimit = 16  # inverter current limit / A
iNominal = 12  # nominal inverter current / A
mu = 80  # factor for barrier function (see below)
i_ref1 = np.array([10, 0, 0])  # exemplary set point i.e. id = 10, iq = 0, i0 = 0 / A
i_ref2 = np.array([5, 0, 0])  # exemplary set point i.e. id = 15, iq = 0, i0 = 0 / A

# plant
L = 2.3e-3  # / H
R = 400e-3  # / Ohm

phase_shift = 5
amp_dev = 1.1


def pairwise(iterable):
    "s -> (s0,s1), (s1,s2), (s2, s3), ..."
    a, b = tee(iterable)
    next(b, None)
    return zip(a, b)


def cal_j_min(phase_shift, amp_dev):
    """
    Calulated the miminum performance for safeopt
    Best case error of all safe boundary scenarios is used (max) to indicate which typ of error tears
    the safe boarder first (the weakest link in the chain)
    """

    ph_list = [phase_shift, 0]
    amp_list = [1, amp_dev]
    return_j_min = np.empty(len(ph_list))
    error_j_min = np.empty(3)
    ph_shift = [0, 120, 240]
    t = np.linspace(0, max_episode_steps * delta_t, max_episode_steps)

    # risetime = 0.0015 -> 15 steps um auf 10A zu kommen: grade = 10/15
    grad = 0.66  # 1e-1
    irefs = [0, i_ref1[0], i_ref2[0]]
    ts = [0, max_episode_steps // 2, max_episode_steps]

    for q in range(len(ph_list)):
        for p in range(3):
            amplitude_sp = np.concatenate([np.full(t1 - t0, r1)
                                           for (r0, t0), (r1, t1) in pairwise(zip(irefs, ts))])
            amplitude = np.concatenate(
                [np.minimum(
                    r0 + grad * np.arange(0, t1 - t0),  # ramp up phase
                    np.full(t1 - t0, r1)  # max amplitude
                ) for (r0, t0), (r1, t1) in pairwise(zip(irefs, ts))])
            mess = amp_list[q] * amplitude * np.cos(
                2 * np.pi * 50 * t + (ph_list[q] * np.pi / 180) + (ph_shift[p] * np.pi / 180))
            sp = amplitude_sp * np.cos(2 * np.pi * 50 * t + (ph_shift[p] * np.pi / 180))
            error_j_min[p] = -np.sum((np.abs((sp - mess)) / iLimit) ** 0.5, axis=0) / max_episode_steps
        return_j_min[q] = np.sum(error_j_min)  # Sum all 3 phases
    return max(return_j_min)


if __name__ == '__main__':

    rew = Reward(i_limit=iLimit, i_nominal=iNominal, mu_c=mu, max_episode_steps=max_episode_steps,
                 obs_dict=[[f'lc.inductor{k}.i' for k in '123'], 'master.phase', [f'master.SPI{k}' for k in 'dq0']])

    #####################################
    # Definitions for the GP
    prior_mean = 0  # 2  # mean factor of the GP prior mean which is multiplied with the first performance of the
    # initial set
    noise_var = 0.001  # 0.001 ** 2  # measurement noise sigma_omega
    prior_var = 2  # prior variance of the GP

    bounds = None
    lengthscale = None
    if adjust == 'Kp':
        bounds = [(0.0001, 0.1)]  # bounds on the input variable Kp
        lengthscale = [.025]  # length scale for the parameter variation [Kp] for the GP

    # For 1D example, if Ki should be adjusted
    if adjust == 'Ki':
        bounds = [(0, 20)]  # bounds on the input variable Ki
        lengthscale = [10]  # length scale for the parameter variation [Ki] for the GP

    # For 2D example, choose Kp and Ki as mutable parameters (below) and define bounds and lengthscale for both of them
    if adjust == 'Kpi':
        bounds = [(0.001, 0.07), (2, 150)]
        lengthscale = [0.012, 30.]

    df_len = pd.DataFrame({'lengthscale': lengthscale,
                           'bounds': bounds,
                           'balanced_load': balanced_load,
                           'barrier_param_mu': mu})

    # The performance should not drop below the safe threshold, which is defined by the factor safe_threshold times
    # the initial performance: safe_threshold = 0.8 means. Performance measurement for optimization are seen as
    # unsafe, if the new measured performance drops below 20 % of the initial performance of the initial safe (!)
    # parameter set
    safe_threshold = 0
    j_min = cal_j_min(phase_shift, amp_dev)  # Used for normalization

    # The algorithm will not try to expand any points that are below this threshold. This makes the algorithm stop
    # expanding points eventually.
    # The following variable is multiplied with the first performance of the initial set by the factor below:
    explore_threshold = 0

    # Factor to multiply with the initial reward to give back an abort_reward-times higher negative reward in case of
    # limit exceeded
    # has to be negative due to normalized performance (regarding J_init = 1)
    abort_reward = 100 * j_min

    # Definition of the kernel
    kernel = GPy.kern.Matern32(input_dim=len(bounds), variance=prior_var, lengthscale=lengthscale, ARD=True)

    #####################################
    # Definition of the controllers
    mutable_params = None
    current_dqp_iparams = None
    if adjust == 'Kp':
        # mutable_params = parameter (Kp gain of the current controller of the inverter) to be optimized using
        # the SafeOpt algorithm
        mutable_params = dict(currentP=MutableFloat(0.04))

        # Define the PI parameters for the current controller of the inverter
        current_dqp_iparams = PI_params(kP=mutable_params['currentP'], kI=12, limits=(-1, 1))

    # For 1D example, if Ki should be adjusted
    elif adjust == 'Ki':
        mutable_params = dict(currentI=MutableFloat(5))
        current_dqp_iparams = PI_params(kP=0.005, kI=mutable_params['currentI'], limits=(-1, 1))

    # For 2D example, choose Kp and Ki as mutable parameters
    elif adjust == 'Kpi':
        mutable_params = dict(currentP=MutableFloat(0.04), currentI=MutableFloat(11.8))
        current_dqp_iparams = PI_params(kP=mutable_params['currentP'], kI=mutable_params['currentI'],
                                        limits=(-1, 1))

    # Define a current sourcing inverter as master inverter using the pi and droop parameters from above
    ctrl = MultiPhaseDQCurrentSourcingController(current_dqp_iparams, ts_sim=delta_t,
                                                 ts_ctrl=undersample * delta_t, name='master', f_nom=net.freq_nom)

    i_ref = MutableParams([MutableFloat(f) for f in i_ref1])
    #####################################
    # Definition of the optimization agent
    # The agent is using the SafeOpt algorithm by F. Berkenkamp (https://arxiv.org/abs/1509.01066) in this example
    # Arguments described above
    # History is used to store results
    agent = SafeOptAgent(mutable_params,
                         abort_reward,
                         j_min,
                         kernel,
                         dict(bounds=bounds, noise_var=noise_var, prior_mean=prior_mean, safe_threshold=safe_threshold,
                              explore_threshold=explore_threshold), [ctrl],
                         dict(master=[[f'lc.inductor{k}.i' for k in '123'], i_ref]), history=FullHistory()
                         )

    #####################################
    # Definition of the environment using a FMU created by OpenModelica
    # (https://www.openmodelica.org/)
    # Using an inverter supplying a load
    # - using the reward function described above as callable in the env
    # - viz_cols used to choose which measurement values should be displayed (here, only the 3 currents across the
    #   inductors of the inverters are plotted. Labels and grid is adjusted using the PlotTmpl (For more information,
    #   see UserGuide)
    # - inputs to the models are the connection points to the inverters (see user guide for more details)
    # - model outputs are the the 3 currents through the inductors and the 3 voltages across the capacitors

    if include_simulate:

        # Defining unbalanced loads sampling from Gaussian distribution with sdt = 0.2*mean
        r_load = Load(R, 0.1 * R, balanced=balanced_load, tolerance=0.1)
        l_load = Load(L, 0.1 * L, balanced=balanced_load, tolerance=0.1)


        # i_noise = Noise([0, 0, 0], [0.0023, 0.0015, 0.0018], 0.0005, 0.32)

        # if no noise should be included:
        # r_load = Load(R, 0 * R, balanced=balanced_load)
        # l_load = Load(L, 0 * L, balanced=balanced_load)

        # i_noise = Noise([0, 0, 0], [0.0, 0.0, 0.0], 0.0, 0.0)

        def reset_loads():
            r_load.reset()
            l_load.reset()


        plotter = PlotManager(agent, save_results=save_results, save_folder=save_folder,
                              show_plots=show_plots)


        def reference_step(t):

            if t >= .05:
                i_ref[:] = i_ref2
            else:
                i_ref[:] = i_ref1

            return partial(l_load.give_value, n=2)(t)


        env = gym.make('openmodelica_microgrid_gym:ModelicaEnv_test-v1',
                       # reward_fun=Reward().rew_fun,
                       reward_fun=rew.rew_fun_c,
                       # time_step=delta_t,
                       viz_cols=[
                           PlotTmpl([[f'lc.inductor{i}.i' for i in '123'], [f'master.SPI{i}' for i in 'abc']],
                                    callback=plotter.xylables_i_abc,
                                    color=[['b', 'r', 'g'], ['b', 'r', 'g']],
                                    style=[[None], ['--']]
                                    ),
                           PlotTmpl([[f'master.m{i}' for i in 'abc']],
                                    callback=lambda fig: plotter.update_axes(fig, title='Simulation',
                                                                             ylabel='$m_{\mathrm{abc}}\,/\,\mathrm{}$')

                                    ),
                           PlotTmpl([[f'master.CVI{i}' for i in 'dq0'], [f'master.SPI{i}' for i in 'dq0']],
                                    callback=plotter.xylables_i_dq0,
                                    color=[['b', 'r', 'g'], ['b', 'r', 'g']],
                                    style=[[None], ['--']]
                                    )
                       ],
                       log_level=logging.INFO,
                       viz_mode='episode',
                       max_episode_steps=max_episode_steps,
                       model_params={'lc.resistor1.R': partial(r_load.give_value, n=0),
                                     'lc.resistor2.R': partial(r_load.give_value, n=1),
                                     'lc.resistor3.R': partial(r_load.give_value, n=2),
                                     'lc.inductor1.L': partial(l_load.give_value, n=0),
                                     'lc.inductor2.L': partial(l_load.give_value, n=1),
                                     'lc.inductor3.L': reference_step},
                       model_path='../../omg_grid/grid.paper.fmu',
                       # model_path='../omg_grid/omg_grid.Grids.Paper_SC.fmu',
                       net=net,
                       history=FullHistory(),
                       action_time_delay=1 * undersample
                       )

        runner = MonteCarloRunner(agent, env)

        runner.run(num_episodes, n_mc=n_MC, visualise=True, prepare_mc_experiment=reset_loads)

        #####################################
        # Results
        best_agent_plt = runner.run_data['last_agent_plt']
        ax = best_agent_plt.axes[0]
        ax.grid(which='both')
        ax.set_axisbelow(True)

        if adjust == 'Ki':
            ax.set_xlabel(r'$K_\mathrm{i}\,/\,\mathrm{(VA^{-1}s^{-1})}$')
            ax.set_ylabel(r'$J$')
            ax.set_ylim([-0.5, 1.5])
        elif adjust == 'Kp':
            ax.set_xlabel(r'$K_\mathrm{p}\,/\,\mathrm{(VA^{-1})}$')
            ax.set_ylabel(r'$J$')

        elif adjust == 'Kpi':
            agent.params.reset()
            ax.set_ylabel(r'$K_\mathrm{i}\,/\,\mathrm{(VA^{-1}s^{-1})}$')
            ax.set_xlabel(r'$K_\mathrm{p}\,/\,\mathrm{(VA^{-1})}$')
            ax.get_figure().axes[1].set_ylabel(r'$J$')
            plt.title('Lengthscale = {}; balanced = '.format(lengthscale, balanced_load))
            # ax.plot([mutable_params['currentP'].val, mutable_params['currentP'].val], bounds[1], 'k-', zorder=1,
            #        lw=4,
            #        alpha=.5)
        best_agent_plt.show()

        if save_results:
            best_agent_plt.savefig(save_folder + '/_agent_plt.pdf')
            best_agent_plt.savefig(save_folder + '/_agent_plt.pgf')
            agent.history.df.to_csv(save_folder + '/_result.csv')
            df_len.to_csv(save_folder + '/_params.csv')

        print('\n Experiment finished with best set: \n\n {}'.format(agent.history.df[:]))
        print('\n Experiment finished with best set: \n')
        print('\n  {} = {}'.format(adjust, agent.history.df.at[np.argmax(agent.history.df['J']), 'Params']))
        print('  Resulting in a performance of J = {}'.format(np.max(agent.history.df['J'])))
        print('\n\nBest experiment results are plotted in the following:')
        print(agent.unsafe)

    if do_measurement:
        #####################################
        # Execution of the experiment
        # Using a runner to execute 'num_episodes' different episodes (i.e. SafeOpt iterations)

        env = TestbenchEnv(num_steps=max_episode_steps, DT=1 / 10000, ref=10, ref2=5,
                           i_limit=iLimit, i_nominal=iNominal, f_nom=60, mu=mu)
        runner = RunnerHardware(agent, env)

        runner.run(num_episodes, visualise=True, save_folder=save_folder)

        print('\n Experiment finished with best set: \n\n {}'.format(agent.history.df[:]))
        print('\n Experiment finished with best set: \n')
        print('\n  {} = {}'.format(adjust, agent.history.df.at[np.argmax(agent.history.df['J']), 'Params']))
        print('  Resulting in a performance of J = {}'.format(np.max(agent.history.df['J'])))
        print('\n\nBest experiment results are plotted in the following:')

        if save_results:
            agent.history.df.to_csv(save_folder + '/_meas_result.csv')
            df_len.to_csv(save_folder + '/_meas_params.csv')

        # Show last performance plot
        best_agent_plt = runner.run_data['last_agent_plt']
        ax = best_agent_plt.axes[0]
        ax.grid(which='both')
        ax.set_axisbelow(True)

        if adjust == 'Ki':
            ax.set_xlabel(r'$K_\mathrm{i}\,/\,\mathrm{(VA^{-1}s^{-1})}$')
            ax.set_ylabel(r'$J$')
        elif adjust == 'Kp':
            ax.set_xlabel(r'$K_\mathrm{p}\,/\,\mathrm{(VA^{-1})}$')
            ax.set_ylabel(r'$J$')
        elif adjust == 'Kpi':
            agent.params.reset()
            ax.set_ylabel(r'$K_\mathrm{i}\,/\,\mathrm{(VA^{-1}s^{-1})}$')
            ax.set_xlabel(r'$K_\mathrm{p}\,/\,\mathrm{(VA^{-1})}$')
            ax.get_figure().axes[1].set_ylabel(r'$J$')
            # plt.plot(bounds[0], [mutable_params['currentP'].val, mutable_params['currentP'].val], 'k-', zorder=1,
            #         lw=4,
            #         alpha=.5)
        best_agent_plt.show()
        if save_results:
            best_agent_plt.savefig(save_folder + '/_meas_agent_plt.pgf')
            best_agent_plt.savefig(save_folder + '/_meas_agent_plt.pdf')
