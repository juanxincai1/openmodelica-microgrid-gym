from functools import partial

import gym
import matplotlib.pyplot as plt
from stochastic.processes import VasicekProcess

from experiments.hp_tune.env.random_load import RandomLoad
from openmodelica_microgrid_gym.env import PlotTmpl
from openmodelica_microgrid_gym.net import Network
from openmodelica_microgrid_gym.util import RandProcess

load = 55  # 28
upper_bound_load = 140
lower_bound_load = 11
net = Network.load('net/net_vctrl_single_inv.yaml')
max_episode_steps = int(2 / net.ts)

"""
 Tescases need to have:
  - Full load
  - (nearly) No load
  - Step up/down
  - Drift up/down
1 second, start at nominal power
"""
time_to_nomPower = 0.1
time_nomPower_drift = 0.32
time_loadshading = 0.587
time_power_ramp_up = 0.741
time_power_ramp_down = 0.985
time_power_Ramp_stop = 1.3
time_drift_down2 = 1.52
time_step_up2 = 1.66
time_drift_down3 = 1.72

R_load = []


def load_step(t):
    """
    Doubles the load parameters
    :param t:
    :param gain: device parameter
    :return: Dictionary with load parameters
    """
    # Defines a load step after 0.01 s
    if time_to_nomPower < t <= time_to_nomPower + net.ts:
        # step to p_nom
        gen.proc.mean = 14
        gen.reserve = 14

    elif time_nomPower_drift < t <= time_nomPower_drift + net.ts:
        # drift
        gen.proc.mean = 40
        gen.proc.speed = 40
        # gen.reserve = 40


    elif time_loadshading < t <= time_loadshading + net.ts:
        # loadshading
        gen.proc.mean = upper_bound_load
        gen.reserve = upper_bound_load
        gen.proc.vol = 25

    elif time_power_ramp_up < t <= time_power_ramp_up + net.ts:
        # drift
        gen.proc.mean = 80
        gen.proc.speed = 10
        # gen.reserve = 40


    elif time_power_ramp_down < t <= time_power_ramp_down + net.ts:
        gen.proc.mean = 30
        gen.proc.speed = 80
        gen.proc.vol = 10
        # gen.reserve = 40

    elif time_power_Ramp_stop < t <= time_power_Ramp_stop + net.ts:
        gen.proc.mean = 30
        gen.proc.speed = 1000
        gen.proc.vol = 100
        # gen.reserve = 40

    elif time_drift_down2 < t <= time_drift_down2 + net.ts:
        gen.proc.mean = 100
        gen.proc.speed = 100
        # gen.reserve = 40

    elif time_step_up2 < t <= time_step_up2 + net.ts:
        gen.proc.mean = 20
        gen.proc.speed = 1000
        gen.reserve = 20

    elif time_drift_down3 < t <= time_drift_down3 + net.ts:
        gen.proc.mean = 50
        gen.proc.speed = 60
        gen.proc.vol = 2
        # gen.reserve = 40

    R_load_sample = gen.sample(t)
    R_load.append(R_load_sample)

    return R_load_sample


if __name__ == '__main__':
    gen = RandProcess(VasicekProcess, proc_kwargs=dict(speed=1000, vol=10, mean=load), initial=load,
                      bounds=(lower_bound_load, upper_bound_load))

    rand_load = RandomLoad(max_episode_steps, net.ts, gen)


    def xylables(fig):
        ax = fig.gca()
        ax.set_xlabel(r'$t\,/\,\mathrm{s}$')
        ax.set_ylabel('$R_{\mathrm{load}}\,/\,\mathrm{\Omega}$')
        ax.grid(which='both')
        ax.set_ylim([lower_bound_load - 2, upper_bound_load + 2])
        # plt.title('Load example drawn from Ornstein-Uhlenbeck process \n- Clipping outside the shown y-range')
        plt.legend()
        fig.show()


    env = gym.make('openmodelica_microgrid_gym:ModelicaEnv_test-v1',
                   net=net,
                   model_params={'r_load.resistor1.R': load_step,  # For use upper function
                                 'r_load.resistor2.R': load_step,
                                 'r_load.resistor3.R': load_step},
                   # model_params={'r_load.resistor1.R': rand_load.random_load_step,         # for check train-random
                   #              'r_load.resistor2.R': rand_load.random_load_step,         # loadstep
                   #              'r_load.resistor3.R': rand_load.random_load_step},
                   viz_cols=[
                       PlotTmpl([f'r_load.resistor{i}.R' for i in '123'],
                                callback=xylables
                                )],
                   model_path='../../omg_grid/grid.paper_loadstep.fmu',
                   max_episode_steps=max_episode_steps)

    env.reset()
    for _ in range(max_episode_steps):
        env.render()

        obs, rew, done, info = env.step(env.action_space.sample())  # take a random action
        if done:
            break
    env.close()

    df_store = env.history.df[['r_load.resistor1.R', 'r_load.resistor2.R', 'r_load.resistor3.R']]
    # df_store.to_pickle('R_load_test_case_2_seconds.pkl')
