from uavf_2024.imaging.imaging_types import ProbabilisticTargetDescriptor, Target3D, CertainTargetDescriptor
from uavf_2024.imaging import TargetTracker, Localizer, Camera
from scipy.spatial.transform import Rotation as R
import cv2 as cv
import numpy as np
import os
import json
from collections import defaultdict
import shutil

if __name__=="__main__":
    root_folder = "/home/forge/ws/src/libuavf_2024/flight_logs/06-01 10:26/image_processor"
    out_folder = "imaging/visualizations/arc_test_601_1_limited"
    try:
        os.makedirs(out_folder)
    except:
        shutil.rmtree(out_folder)
    tracker = TargetTracker()
    # for frame_folder in os.listdir(root_folder):
    for i in range(779, 818):
        if i in [792,803,804,809,810]:
            continue
        frame_folder = f"img_{i}"
        data = json.load(open(f"{root_folder}/{frame_folder}/data.json"))
        preds_3d_dicts = data["preds_3d"] 
        preds_3d = []
        for p in preds_3d_dicts:
            det_id = p['id'].split('/')[1]
            crop_img = cv.imread(f"{root_folder}/{frame_folder}/{det_id}/input.png")
            file_contents = open(f"{root_folder}/{frame_folder}/{det_id}/descriptor.txt").read()
            channels = cv.split(crop_img)
            hist = np.empty((3,256))
            for i, chan in enumerate(channels):
                hist[i] = cv.calcHist([chan], [0], None, [256], [0, 256])[:,0]
            preds_3d.append(Target3D(
                np.array(p['position']),
                ProbabilisticTargetDescriptor.from_string(file_contents),
                id = f"{frame_folder}/{det_id}",
                hist=hist
            ))
        tracker.update(preds_3d)

    # targets = [
    #     CertainTargetDescriptor('red','star','green','Q'),
    #     CertainTargetDescriptor('blue','semicircle','orange','S'),
    #     CertainTargetDescriptor('brown','pentagon','orange','C'),
    #     CertainTargetDescriptor('red','rectangle','green','T'),
    #     CertainTargetDescriptor('orange','quartercircle','blue','3')
    # ]
    targets = [
        CertainTargetDescriptor('red','star','green','Q'),
        CertainTargetDescriptor('blue','semicircle','orange','S'),
        CertainTargetDescriptor('brown','pentagon','orange','C'),
        CertainTargetDescriptor('red','rectangle','green','T'),
        CertainTargetDescriptor('orange','quartercircle','blue','3')
    ]

    tracks = tracker.estimate_positions(targets)

    for target, track in zip(targets, tracks):
        print(f"Target {target} on track {track.id}")

    for pos in tracker.tracks:
        os.makedirs(f"{out_folder}/{pos.id}", exist_ok=True)
        print(f"Track {pos.id}")
        print(f"Contributing measurements: {pos.contributing_measurement_ids()}")
        # for each contributing measurement, reproject the 3D position to the image plane and display the image with the reprojected point, bounding box, and descriptor
        contributing_frame_mapping = defaultdict(list)
        for measurement_id in pos.contributing_measurement_ids():
            frame_folder, det_id = measurement_id.split('/')
            contributing_frame_mapping[frame_folder].append(det_id)
        
        for frame_folder, det_ids in contributing_frame_mapping.items():
            img = cv.imread(f"{root_folder}/{frame_folder}/bounding_boxes.png")
            for i, det_id in enumerate(det_ids):
                descriptor_str = open(f"{root_folder}/{frame_folder}/{det_id}/descriptor.txt").read()
                descriptor = ProbabilisticTargetDescriptor.from_string(descriptor_str)
                cv.putText(img, f"{det_id}: {descriptor.collapse_to_certain()}", (10,60+30*i), cv.FONT_HERSHEY_SIMPLEX, 1, (255,0,0), 2)

            # reproject
            data = json.load(open(f"{root_folder}/{frame_folder}/data.json"))
            drone_pos = np.array(data["drone_position"])
            drone_quaternion = R.from_quat(data["drone_q"])
            cam_angles = np.array([data["gimbal_yaw"], data["gimbal_pitch"], data["gimbal_roll"]])
            zoom_level = data.get("zoom_level", 1)
            localizer = Localizer.from_focal_length(
                Camera.focalLengthFromZoomLevel(zoom_level),
                (img.shape[1], img.shape[0]),
                Localizer.drone_initial_directions(),
                2
            )
            cam_rot = Camera.orientation_in_world_frame(drone_quaternion, cam_angles)
            for other_track in tracker.tracks:
                reprojected = localizer.coords_to_2d(other_track.position, (drone_pos, cam_rot))
                color = (255,255,0) if other_track.id==pos.id else (0,0,255)
                cv.circle(img, reprojected, 5, color, -1)
                pos_str = ",".join(f'{coord:.01f}' for coord in other_track.position)
                cv.putText(img, f"{other_track.id}, {pos_str}", reprojected, cv.FONT_HERSHEY_SIMPLEX, 1, color, 2)

            in_bounds = 0 <= reprojected[0] < img.shape[1] and 0 <= reprojected[1] < img.shape[0]
            color = (255,0,0) if in_bounds else (0,0,255)
            cv.putText(img, str(reprojected), (10,30), cv.FONT_HERSHEY_SIMPLEX, 1, color, 2)


            cv.imwrite(f"{out_folder}/{pos.id}/{frame_folder}.png", img)
