from matplotlib import pyplot as plt

from config.config import TASK_CONFIG, ROBOT_PORTS
import os
import cv2
import h5py
import argparse
from tqdm import tqdm
from time import sleep, time
from training.utils import pwm2pos, pwm2vel

from robot import Robot

# parse the task name via command line
parser = argparse.ArgumentParser()
parser.add_argument('--task', type=str, default='task1')
parser.add_argument('--num_episodes', type=int, default=1)
args = parser.parse_args()
task = args.task
num_episodes = args.num_episodes

cfg = TASK_CONFIG


def capture_image(cam):
    # Capture a single frame
    _, frame = cam.read()
    # Generate a unique filename with the current date and time
    image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    # Define your crop coordinates (top left corner and bottom right corner)
    x1, y1 = 400, 0  # Example starting coordinates (top left of the crop rectangle)
    x2, y2 = 1600, 900  # Example ending coordinates (bottom right of the crop rectangle)
    # Crop the image
    image = image[y1:y2, x1:x2]
    # Resize the image
    image = cv2.resize(image, (cfg['cam_width'], cfg['cam_height']), interpolation=cv2.INTER_AREA)

    return image


if __name__ == "__main__":
    cam_ls = []
    # init
    for port in cfg['camera_port']:
        cam = cv2.VideoCapture(port)
        if not cam.isOpened():
            raise IOError("Cannot open camera")
        cam_ls.append(cam)
    # Check if the camera opened successfully
    # init follower
    follower = Robot(device_name=ROBOT_PORTS['follower'])
    # init leader
    leader = Robot(device_name=ROBOT_PORTS['leader'])
    leader.set_trigger_torque()

    
    for i in range(num_episodes):
        # bring the follower to the leader and start camera
        for i in range(50):
            follower.set_goal_pos(leader.read_position())
            for cam in cam_ls:
                _ = capture_image(cam)
        os.system('say "go"')
        # init buffers
        obs_replay = []
        action_replay = []
        for i in tqdm(range(cfg['episode_len'])):
            # observation
            qpos = leader.read_position()
            qvel = leader.read_velocity()
            image_ls = []
            for cam in cam_ls:
                image_ls.append(capture_image(cam))
            dic = {}
            for i in range(len(image_ls)):
                dic.update({cfg['camera_names'][i]: image_ls[i]})
            obs = {
                'qpos': pwm2pos(qpos),
                'qvel': pwm2vel(qvel),
                'images': dic
            }
            # action (leader's position)
            action = leader.read_position()
            # apply action
            print(action)
            follower.set_goal_pos(action)
            action = pwm2pos(action)
            # store data
            obs_replay.append(obs)
            action_replay.append(action)

        os.system('say "stop"')

        # disable torque
        #leader._disable_torque()
        #follower._disable_torque()

        # create a dictionary to store the data
        data_dict = {
            '/observations/qpos': [],
            '/observations/qvel': [],
            '/action': [],
        }
        # there may be more than one camera
        for cam_name in cfg['camera_names']:
                data_dict[f'/observations/images/{cam_name}'] = []

        # store the observations and actions
        for o, a in zip(obs_replay, action_replay):
            data_dict['/observations/qpos'].append(o['qpos'])
            data_dict['/observations/qvel'].append(o['qvel'])
            data_dict['/action'].append(a)
            # store the images
            for cam_name in cfg['camera_names']:
                data_dict[f'/observations/images/{cam_name}'].append(o['images'][cam_name])

        t0 = time()
        max_timesteps = len(data_dict['/observations/qpos'])
        # create data dir if it doesn't exist
        data_dir = os.path.join(cfg['dataset_dir'], task)
        if not os.path.exists(data_dir): os.makedirs(data_dir)
        # count number of files in the directory
        idx = len([name for name in os.listdir(data_dir) if os.path.isfile(os.path.join(data_dir, name))])
        dataset_path = os.path.join(data_dir, f'episode_{idx}')
        # save the data
        with h5py.File(dataset_path + '.hdf5', 'w', rdcc_nbytes=1024 ** 2 * 2) as root:
            root.attrs['sim'] = False
            obs = root.create_group('observations')
            image = obs.create_group('images')
            for cam_name in cfg['camera_names']:
                _ = image.create_dataset(cam_name, (max_timesteps, cfg['cam_height'], cfg['cam_width'], 3), dtype='uint8',
                                        chunks=(1, cfg['cam_height'], cfg['cam_width'], 3), )
            qpos = obs.create_dataset('qpos', (max_timesteps, cfg['state_dim']))
            qvel = obs.create_dataset('qvel', (max_timesteps, cfg['state_dim']))
            # image = obs.create_dataset("image", (max_timesteps, 240, 320, 3), dtype='uint8', chunks=(1, 240, 320, 3))
            action = root.create_dataset('action', (max_timesteps, cfg['action_dim']))
            
            for name, array in data_dict.items():
                root[name][...] = array
    
    leader._disable_torque()
    follower._disable_torque()
