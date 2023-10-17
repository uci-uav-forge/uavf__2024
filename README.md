# UAV Forge's ROS2 package for GN&C and Aerial Imagery Object Detection.

## Dev Container Setup
1. Clone the repo
2. In VSCode, open the command palette and run `rebuild and reopen in dev container`
3. To verify your setup, run `run_tests.sh`

## Usage

1. Refer to `sim_instructions.md` for instructions on starting and running the simulation.


## Install instructions

### Install required and local Python libraries

1. cd into this repo's root directory.

2. Run:
	```
	pip install -e .
	```


### Dev container

1. Open this project in vscode
2. Install the "Dev Containers" extension
3. Open the command pallete (ctrl-shift-p), then search for and execute "Dev Containers: (Re-)build and Reopen in Container"
4. Congratulations, you get to skip all those tedious steps to install ROS 2 manually, and your environment is isolated from the rest of your computer
5. To make downloading dependencies reproducible, add any important software installation steps to the Dockerfile in this repo.
6. To use git inside the docker container, you may have to manually log in to GitHub again if the built-in credential forwarding isn't working. I recommend using the [GitHub CLI](https://cli.github.com/) to do this.
7. If you want to use the simulator:
	1. Follow instructions in `sim_instructions.md`.
	2. If you want it to run it in a GUI, one way is using the remote desktop environment in the dev container. Open `localhost:6080` in a web browser, then enter password `vscode`, then use the menu in the bottom left to open a terminal, `cd /home/ws/PX4-Autopilot`, then run `make px4_sitl gazebo-classic`.
	3. The X sockets should also be mounted and should work if you run `xhost +` on your machine.


I copied a lot of the config from this tutorial: https://docs.ros.org/en/foxy/How-To-Guides/Setup-ROS-2-with-VSCode-and-Docker-Container.html


### Manual

(WIP). It's recommended to use the Dockerfile for development.