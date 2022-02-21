import gym
import gym_potter
import rospy
import time
import os


time.sleep(5)
os.environ['ROS_MASTER_URI'] = "http://localhost:{}/".format(11310 + 1)
rospy.init_node('Potter_Circuit_Simple-v0'.replace('-', '_') + "_w{}".format(1))
env = gym.make('Potter_Circuit_Simple-v0', observation_mode=0, continuous=True)
time.sleep(5)

observation = env.reset()

for _ in range(100):
    action = [1.0, 1.0]
    observation, reward, done, info = env.step(action)

    if done:
        observation = env.reset()

env.close()
