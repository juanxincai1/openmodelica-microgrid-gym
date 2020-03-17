"""
This class will handle the execution
"""
from gym import Env

from gym_microgrid.agents import Agent


class Runner:
    def __init__(self, agent: Agent, env: Env):
        self.agent = agent
        self.env = env

    def run(self, n_episodes=10):
        self.agent.reset()

        for episode in range(n_episodes):
            obs = self.env.reset()

            done, r = False, None
            while not done:
                self.agent.observe(r, done)
                act = self.agent.act(obs)
                obs, done, r = self.env.step(act)
