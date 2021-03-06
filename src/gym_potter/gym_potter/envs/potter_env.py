#! /usr/bin/env python3

import rospy
import gym
import numpy as np
import math
import time
import cv2
from geometry_msgs.msg import Twist, Point, Pose
from sensor_msgs.msg import CompressedImage
from sensor_msgs.msg import LaserScan
from nav_msgs.msg import Odometry
from std_srvs.srv import Empty
from gym import spaces
from gym.utils import seeding
from gym_potter.envs.mytf import euler_from_quaternion
from gym_potter.envs import Respawn
import warnings
warnings.simplefilter("ignore")

STATE_H, STATE_W = 64, 64

class PotterEnv(gym.Env):
    def __init__(self, observation_mode=0, max_env_size=None, continuous=False, observation_size=24,
                 action_size=5, min_range=0.13, max_range=3.5, min_ang_vel=-1.5, max_ang_vel=1.5, min_linear_vel=0.,
                 max_linear_vel=2.0, goalbox_distance=0.35, collision_distance=0.17, reward_goal=200.,
                 reward_collision=-20, angle_out=250, goal_list=None):

        self.goal_x = 0
        self.goal_y = 0
        self.heading = 0
        self.image = 0
        self.initGoal = True
        self.get_goalbox = False
        self.position = Pose()

        self.pub_cmd_vel = rospy.Publisher('/cmd_vel', Twist, queue_size=5)
        self.sub_odom = rospy.Subscriber('/odom', Odometry, self.getOdometry)
        
        self.reset_proxy = rospy.ServiceProxy('gazebo/reset_simulation', Empty)
        self.unpause_proxy = rospy.ServiceProxy('gazebo/unpause_physics', Empty)
        self.pause_proxy = rospy.ServiceProxy('gazebo/pause_physics', Empty)
        self.respawn_goal = Respawn()

        goal_list = np.asarray([np.random.uniform((-1.5, -1.5), (1.5, 1.5)) for _ in range(50)])
        self.respawn_goal.setGoalList(goal_list)

        self.observation_mode = observation_mode
        self.observation_size = observation_size
        self.min_range = min_range
        self.max_range = max_range
        self.min_ang_vel = min_ang_vel
        self.max_ang_vel = max_ang_vel
        self.min_linear_vel = min_linear_vel
        self.max_linear_vel = max_linear_vel
        self.goalbox_distance = goalbox_distance
        self.collision_distance = collision_distance
        self.reward_goal = reward_goal
        self.reward_collision = reward_collision
        self.angle_out = angle_out
        self.continuous = continuous
        self.max_env_size = max_env_size

        if self.continuous:
            low, high, shape_value = self.get_action_space_values()
            self.action_space = spaces.Box(low=low, high=high)
        else:
            self.action_space = spaces.Discrete(action_size)
            ang_step = max_ang_vel / ((action_size - 1) / 2)
            self.actions = [((action_size - 1) / 2 - action) * ang_step for action in range(action_size)]
        
        if observation_mode == 1:
            self.sub_image = rospy.Subscriber('/camera/color/image_raw/compressed', CompressedImage, self.getImage, queue_size=10)
            
        low, high, shape = self.get_observation_space_values()
        print(f"Dimensions: low = {low}, high = {high}. Shape = {shape}")

        self.num_timesteps = 0
        self.lidar_distances = None
        self.ang_vel = 0
        self.linear_vel = 0

        self.start_time = time.time()
        self.last_step_time = self.start_time
        self.old_distance = self._getGoalDistace()

        self.seed()

    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def get_action_space_values(self):
        low = np.array([self.min_ang_vel, self.min_linear_vel])
        high = np.array([self.max_ang_vel, self.max_linear_vel])
        shape_value = low.shape
        return low, high, shape_value

    def get_observation_space_values(self):
        if self.observation_mode == 0:
            low = np.append(np.full(self.observation_size, self.min_range), np.array([-math.pi, 0], dtype=np.float32))
            high = np.append(np.full(self.observation_size, self.max_range), np.array([math.pi, self.max_env_size], dtype=np.float32))
            shape = low.shape
            self.observation_space = spaces.Box(low=low, high=high)
        else:
            low = 0
            high = 255
            shape =(STATE_H, STATE_W, 3)
            self.observation_space = spaces.Box(low=low, high=high, shape=shape)
        return low, high, shape

    def _getGoalDistace(self):
        goal_distance = round(math.hypot(self.goal_x - self.position.x, self.goal_y - self.position.y), 2)
        return goal_distance

    def getOdometry(self, odom):
        self.position = odom.pose.pose.position
        orientation = odom.pose.pose.orientation
        orientation_list = [orientation.x, orientation.y, orientation.z, orientation.w]
        _, _, yaw = euler_from_quaternion(orientation_list)
        goal_angle = math.atan2(self.goal_y - self.position.y, self.goal_x - self.position.x)

        heading = goal_angle - yaw
        if heading > math.pi:
            heading -= 2 * math.pi

        elif heading < -math.pi:
            heading += 2 * math.pi

        self.heading = heading

    def getImage(self, image):
        np_arr = np.fromstring(image.data, np.uint8)
        self.image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        cv2.imshow('cv_img', self.image)
        cv2.waitKey(2)


    def get_time_info(self):
        time_info = time.strftime("%H:%M:%S", time.gmtime(time.time() - self.start_time))
        time_info += '-' + str(self.num_timesteps)
        return time_info

    def episode_finished(self):
        pass

    def preprocess_lidar_distances(self, scan_range):
        return scan_range

    def get_env_state(self):
        if self.observation_mode == 0:
            return self.lidar_distances
        elif self.observation_mode == 1:
            return cv2.cvtColor(self.image, cv2.COLOR_BGR2RGB )

    def getState(self, scan):
        scan_range = []
        heading = self.heading
        done = False

        for i in range(len(scan.ranges)):
            if scan.ranges[i] == float('Inf'):
                scan_range.append(self.max_range)
            elif np.isnan(scan.ranges[i]):
                scan_range.append(self.min_range)
            else:
                scan_range.append(scan.ranges[i])

        self.lidar_distances = self.preprocess_lidar_distances(scan_range)
        time_info = self.get_time_info()
        current_distance = self._getGoalDistace()

        if min(self.lidar_distances) < self.collision_distance:
            # print(f'{time_info}: Collision!!')
            done = True

        if abs(heading) > math.radians(self.angle_out):
            # print(f'{time_info}: Out of angle')
            done = True

        if current_distance < self.goalbox_distance:
            if not done:
                # print(f'{time_info}: Goal!!')
                self.get_goalbox = True
                if self.respawn_goal.last_index is (self.respawn_goal.len_goal_list - 1):
                    done = True
                    self.episode_finished()

        if self.observation_mode == 0:
            return self.get_env_state() + [heading, current_distance], done
        else:
            return self.get_env_state(), done

    def navigationReward(self):
        actual_distance = self._getGoalDistace()
        if self.old_distance > actual_distance:
            reward = (self.old_distance - actual_distance) * 100.
            self.old_distance = actual_distance
        else:
            reward = 0.
        return reward

    def setReward(self, done):
        if self.get_goalbox:
            reward = self.reward_goal
            self.pub_cmd_vel.publish(Twist())
            self.goal_x, self.goal_y = self.respawn_goal.getPosition(True, delete=True)
            self.goal_distance = self._getGoalDistace()
            self.get_goalbox = False
        elif done:
            reward = self.reward_collision =- 20.
            self.pub_cmd_vel.publish(Twist())
            if self.respawn_goal.last_index != 0:
                self.respawn_goal.initIndex()
                self.goal_x, self.goal_y = self.respawn_goal.getPosition(True, delete=True)
                self.goal_distance = self._getGoalDistace()
        else:
            reward = self.navigationReward()
        return reward

    def set_ang_vel(self, action):
        if self.continuous:
            self.ang_vel = action
        else:
            self.ang_vel = self.actions[action]

    def set_linear_vel(self, action):
        if self.continuous:
            self.linear_vel = action
        else:
            self.linear_vel = self.actions[action]

    def step(self, action):
        self.set_ang_vel(np.clip(action[0], self.min_ang_vel, self.max_ang_vel))
        self.set_linear_vel(np.clip(action[1], self.min_linear_vel, self.max_linear_vel))

        vel_cmd = Twist()
        vel_cmd.linear.x = self.linear_vel
        vel_cmd.angular.z = self.ang_vel
        self.pub_cmd_vel.publish(vel_cmd)

        data = None
        while data is None:
            try:
                data = rospy.wait_for_message('scan', LaserScan, timeout=5)
            except:
                pass

        state, done = self.getState(data)
        reward = self.setReward(done)
        self.num_timesteps += 1
        return np.asarray(state), reward, done, {}

    def reset(self, new_random_goals=False):
        if new_random_goals:
            self.respawn_goal.setGoalList(np.asarray([np.random.uniform((-1., -1.), (1., 1.)) for _ in range(50)]))

        rospy.wait_for_service('gazebo/reset_simulation')
        try:
            self.reset_proxy()
        except rospy.ServiceException:
            print("gazebo/reset_simulation service call failed")

        data = None
        while data is None:
            try:
                data = rospy.wait_for_message('scan', LaserScan, timeout=5)
            except:
                pass

        if self.initGoal:
            self.goal_x, self.goal_y = self.respawn_goal.getPosition()
            self.initGoal = False
            time.sleep(1)
        else:
            self.goal_x, self.goal_y = self.respawn_goal.getPosition(True, delete=True)

        self.goal_distance = self._getGoalDistace()
        self.old_distance = self._getGoalDistace()
        state, _ = self.getState(data)

        return np.asarray(state)

    def render(self, mode=True):
        pass

    def close(self):
        self.reset()
