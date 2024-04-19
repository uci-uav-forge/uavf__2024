from uavf_2024.imaging import DroneTracker, BoundingBox
import unittest
import numpy as np
from numpy import cos, pi, sin, tan
from scipy.spatial.transform import Rotation as R
import matplotlib.pyplot as plt
import os
from tqdm import tqdm

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

class TestDroneTracker(unittest.TestCase):
    def test_stationary_target(self):
        # object should be radius ~0.35 at the origin, not moving
        resolution = (1920,1080)
        fov = 90
        focal_len_pixels = resolution[0]/(2*tan(fov/2))
        filter = DroneTracker(resolution, focal_len_pixels)

        n_cam_samples = 20
        # make camera poses in a circle around the origin
        cam_pos_radius = 10
        cam_positions = [cam_pos_radius*np.array([sin(2*pi*i/n_cam_samples),0,-cos(2*pi*i/n_cam_samples)]) for i in range(n_cam_samples)]
        # make rotations that point the camera at the origin
        cam_rotations = [R.from_euler('xyz', [0, -2*pi*i/n_cam_samples, 0]) for i in range(n_cam_samples)]

        # visualize the camera positions
        plt.figure()
        ax = plt.axes()
        ax.set_xlim(-cam_pos_radius,cam_pos_radius)
        ax.set_ylim(-cam_pos_radius,cam_pos_radius)
        ax.plot([0], [0], [0], 'ro')
        for cam_pos, cam_rot in zip(cam_positions, cam_rotations):
            look_direction = cam_rot.apply([0,0,1])
            ax.scatter(cam_pos[0], cam_pos[2])
            ax.plot([cam_pos[0], cam_pos[0]+look_direction[0]], [cam_pos[2], cam_pos[2]+look_direction[2]])

        os.makedirs(f'{CURRENT_DIR}/visualizations/drone_tracker', exist_ok=True)
        os.makedirs(f'{CURRENT_DIR}/visualizations/drone_tracker/particles', exist_ok=True)
        plt.savefig(f'{CURRENT_DIR}/visualizations/drone_tracker/test_camera_positions.png')

        plt.figure()
        covariances = []
        for cam_pos, cam_rot in tqdm(zip(cam_positions, cam_rotations)):
            # make a measurement
            r = 20
            measurements = [BoundingBox(960,540,2*r,2*r)]
            filter.predict(0.5)
            if len(filter.tracks) > 0:
                particles_fig = filter.tracks[0].filter.visualize()
                particles_fig.savefig(f'{CURRENT_DIR}/visualizations/drone_tracker/particles/particles_{len(covariances)}a.png')
            filter.update((cam_pos, cam_rot), measurements)

            particles_fig = filter.tracks[0].filter.visualize()
            particles_fig.savefig(f'{CURRENT_DIR}/visualizations/drone_tracker/particles/particles_{len(covariances)}b.png')
            del particles_fig
            covariances.append(np.diag(filter.tracks[0].filter.covariance()))

        labels = [
            'x', 'y', 'z', 'vx', 'vy', 'vz', 'r'
        ]

        for i in range(len(covariances[0])):
            plt.plot([c[i] for c in covariances], label=labels[i])
        plt.legend()
        plt.title("Covariance vs timestep")
        plt.savefig(f'{CURRENT_DIR}/visualizations/drone_tracker/test_covariances.png')


        self.assertTrue(len(filter.tracks) == 1)
        # check that the filter converged to the correct position
        final_state = filter.tracks[0].filter.mean()
        self.assertTrue(np.allclose(final_state[:3], [0,0,0], atol=0.1), f"filter converged to {final_state}")

if __name__ == '__main__':
    unittest.main()