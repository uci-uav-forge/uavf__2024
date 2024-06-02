from uavf_2024.imaging.imaging_types import ProbabilisticTargetDescriptor, Target3D, CertainTargetDescriptor
from uavf_2024.imaging import TargetTracker, Localizer, Camera
from scipy.spatial.transform import Rotation as R
import cv2 as cv
import numpy as np
import os
import json
from collections import defaultdict

if __name__=="__main__":
    root_folder = "imaging/2024_test_data/arc_test_530"
    out_folder = "imaging/visualizations/arc_test_530"
    os.makedirs(out_folder, exist_ok=True)
    tracker = TargetTracker()
    for frame_folder in os.listdir(root_folder):
        data = json.load(open(f"{root_folder}/{frame_folder}/data.json"))
        preds_3d_dicts = data["preds_3d"] 
        for p in preds_3d_dicts:
            det_id = p['id'].split('/')[1]
            file_contents = open(f"{root_folder}/{frame_folder}/{det_id}/descriptor.txt").read()
            tracker.update([Target3D(
                np.array(p['position']),
                ProbabilisticTargetDescriptor.from_string(file_contents),
                id = f"{frame_folder}/{det_id}"
            )])

    targets = [
        CertainTargetDescriptor('red','pentagon','orange','F'),
        CertainTargetDescriptor('red','rectangle','white','T'),
        CertainTargetDescriptor('black','pentagon','white','G'),
        CertainTargetDescriptor('green','triangle','white','7'),
        CertainTargetDescriptor('purple','semicircle','blue','R')
    ]

    positions = tracker.estimate_positions(targets)

    for target, pos in zip(targets, positions):
        target_name = str(target)
        os.makedirs(f"{out_folder}/{target_name}", exist_ok=True)
        print(f"Target {target} is at position {pos}")
        print(f"Contributing measurements: {pos.contributing_measurement_ids()}")
        # for each contributing measurement, reproject the 3D position to the image plane and display the image with the reprojected point, bounding box, and descriptor
        contributing_frame_mapping = defaultdict(list)
        for measurement_id in pos.contributing_measurement_ids():
            frame_folder, det_id = measurement_id.split('/')
            contributing_frame_mapping[frame_folder].append(det_id)
        
        for frame_folder, det_ids in contributing_frame_mapping.items():
            img = cv.imread(f"{root_folder}/{frame_folder}/bounding_boxes.png")
            data = json.load(open(f"{root_folder}/{frame_folder}/data.json"))
            drone_pos = np.array(data["drone_position"])
            drone_quaternion = R.from_quat(data["drone_q"])
            cam_angles = np.array([data["gimbal_yaw"], data["gimbal_pitch"], data["gimbal_roll"]])
            zoom_level = data.get("zoom_level", 1)

            # reproject
            localizer = Localizer.from_focal_length(
                Camera.focalLengthFromZoomLevel(zoom_level),
                (img.shape[1], img.shape[0]),
                Localizer.drone_initial_directions(),
                2
            )
            cam_rot = Camera.orientation_in_world_frame(drone_quaternion, cam_angles)
            reprojected = localizer.coords_to_2d(pos.position, (drone_pos, cam_rot))
            cv.circle(img, reprojected, 15, (0,0,255), 2)
            in_bounds = 0 <= reprojected[0] < img.shape[1] and 0 <= reprojected[1] < img.shape[0]
            color = (255,0,0) if in_bounds else (0,0,255)
            cv.putText(img, str(reprojected), (10,30), cv.FONT_HERSHEY_SIMPLEX, 1, color, 2)

            for i, det_id in enumerate(det_ids):
                descriptor_str = open(f"{root_folder}/{frame_folder}/{det_id}/descriptor.txt").read()
                descriptor = ProbabilisticTargetDescriptor.from_string(descriptor_str)
                cv.putText(img, f"{det_id}: {descriptor.collapse_to_certain()}", (10,60+30*i), cv.FONT_HERSHEY_SIMPLEX, 1, (255,0,0), 2)

            cv.imwrite(f"{out_folder}/{target_name}/{frame_folder}.png", img)
