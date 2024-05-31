#!/bin/bash

# Setup
cd ~/ws
source install/setup.sh
colcon build --merge-install
sudo chmod 666 /dev/ttyACM0
ros2 launch mavros px4.launch fcu_url:=/dev/ttyACM0:921600

# ESC Telem
cd ~/ws/src/libuavf_2024
sudo chmod 666 /dev/ttyTHS1
# tmux it
py esc_read.py

# Camera Test
cd ~/ws/src/libuavf_2024/scripts/perception_clients
py test_only_camera.py

# Perception Node
ros2 launch src/libuavf_2024/launches/imaging_multiple_demo.launch