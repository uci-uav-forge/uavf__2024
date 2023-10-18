# Author: Eesh Vij
# Date: 2023-10-18
# Purpose: Dynamically create Dockerfile based on correct system archiecture

import platform
import pathlib

arm64image = "arm64v8/ros:humble"
x86image = "ros:humble"

# additional arm64 commands
arm64commands = ["RUN pip install --force-reinstall -v torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2\n"]

# Get system architecture
print(f"System: {platform.system()}")
print(f"System Architecture: {platform.machine()}")
if platform.machine() == "arm64":
    arm64 = True
else:
    arm64 = False
# Get current directory
current_dir = pathlib.Path(__file__).parent.absolute()
print(f"Current Directory: {current_dir}")
# Read Dockerfile template
data = None
with open(str(current_dir) + "/Dockerfile", "r") as file:
    print("Generating Dockerfile...")
    data = file.readlines()

if arm64:
    data[2] = f"FROM {arm64image}\n"
    data.append("\n")
    data.extend(arm64commands)
else:
    data[2] = f"FROM {x86image}\n"

# Write to Dockerfile
with open(str(current_dir) + "/.devcontainer/Dockerfile", "w") as file:
    print("Writing to Dockerfile...")
    file.writelines(data)