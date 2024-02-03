import unittest
from uavf_2024.imaging.localizer import Localizer
from uavf_2024.imaging.area_coverage import AreaCoverageTracker
from uavf_2024.imaging.image_processor import ImageProcessor
from uavf_2024.imaging.tracker import TargetTracker
from uavf_2024.imaging.imaging_types import Image, TargetDescription, Target3D, COLORS, SHAPES, LETTERS
from uavf_2024.imaging.utils import calc_match_score
import os
import numpy as np
import shutil
import cv2 as cv
import random

CURRENT_FILE_PATH = os.path.dirname(os.path.realpath(__file__))


def stringify_target_description(desc: TargetDescription):
    return f"{COLORS[np.argmax(desc.shape_col_probs)]} {SHAPES[np.argmax(desc.shape_probs)]}, {COLORS[np.argmax(desc.letter_col_probs)]} {LETTERS[np.argmax(desc.letter_probs)]}"

def csv_to_np(csv_str: str, delim: str = ","):
    '''
    Parses strings like "1,2,3" or "1:2:3" into numpy array [1,2,3]
    '''
    return np.array(
        [
            int(x) for x in
            csv_str.split(delim)
        ]
    )

class TestPipeline(unittest.TestCase):
    def test_with_sim_dataset(self, verbose: bool = True):
        '''
        Runs the entire pipeline on the simulated dataset that includes multiple
        images annotated with the 3D position of the targets, and selects 100
        random subsets of 5 objects to choose as the drop targets,
        and compares the estimated positions of the targets to the ground truth
        to see how many are within a certain distance of the ground truth.
        '''
        FOV = 50.94 # in degrees, 
        # FOV IS NOT THE SAME AS THE CAMERA IN GODOT. 
        # This is the horizontal FOV, the camera in godot has a vertical FOV of 30
        # conversion formula is 2*arctan(16/9*tan(h_fov/2))

        # The resolution of the camera in godot is 1920x1080
        RES = (1920, 1080)
        target_localizer = Localizer(
            FOV,
            RES
        )
        area_tracker = AreaCoverageTracker(
            FOV,
            RES
        )
        if verbose:
            debug_output_folder = f"{CURRENT_FILE_PATH}/imaging_data/visualizations/integ_test"
            if os.path.exists(debug_output_folder):
                shutil.rmtree(debug_output_folder)
        else:
            debug_output_folder = None
        image_processor = ImageProcessor(debug_output_folder)


        tracker = TargetTracker()
        
        images_dirname = f"{CURRENT_FILE_PATH}/imaging_data/3d_dataset/images"
        predictions_3d: list[Target3D] =  []
        # sort by image number (e.g. img_2 is before img_10 despite lexigraphical ordering)
        def sort_key(file_name: str):
            return int(file_name.split("_")[0][5:])
        for file_name in sorted(os.listdir(images_dirname), key=sort_key):
            img = Image.from_file(f"{images_dirname}/{file_name}")
            pose_strs = file_name.split(".")[0].split("_")[1:]
            cam_position = csv_to_np(pose_strs[0])
            cam_angles = csv_to_np(pose_strs[1])

            predictions = image_processor.process_image(img)
            area_tracker.update(np.concatenate([cam_position, cam_angles]), label=file_name.split("_")[0])

            if verbose:
                bounding_boxes_image_path = f"{debug_output_folder}/img_{sort_key(file_name)}/bounding_boxes.png"
                boxes_img = cv.imread(bounding_boxes_image_path)

            # calculate 3d positions for all detections, and draw them on the debug image
            for pred in predictions:
                pred_3d = target_localizer.prediction_to_coords(pred, np.concatenate([cam_position, cam_angles]))
                predictions_3d.append(pred_3d)

                if not verbose: continue
                x,y,w,h, = pred.x, pred.y, pred.width, pred.height
                x3, y3, z3 = pred_3d.position
                cv.putText(boxes_img, f"{x3:.01f}, {y3:.01f}, {z3:.01f}", (x,y+h+20), cv.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)

            if verbose:
                cv.imwrite(bounding_boxes_image_path, boxes_img)


        area_tracker.visualize(f"{debug_output_folder}/coverage.png", 5000)
        tracker.update(predictions_3d)


        POSITION_ERROR_ACCEPTABLE_BOUND = 2 

        NUM_TARGET_SUBSETS = 100

        scores_across_subsets = []

        for i in range(NUM_TARGET_SUBSETS):
            ground_truth: list[Target3D] = []
            with open(f"{CURRENT_FILE_PATH}/imaging_data/3d_dataset/labels.txt", "r") as f:
                for line in random.sample(f.readlines(), 5):
                    label, location_str = line.split(" ")
                    shape_name, alphanumeric, shape_col, letter_col = label.split(",")

                    ground_truth.append(
                        Target3D(
                            csv_to_np(location_str),
                            TargetDescription(
                                np.eye(9)[SHAPES.index(shape_name)],
                                np.eye(36)[LETTERS.index(alphanumeric)],
                                np.eye(8)[COLORS.index(shape_col)],
                                np.eye(8)[COLORS.index(letter_col)]
                            )
                        )
                    )

            closest_tracks = tracker.estimate_positions([t.description for t in ground_truth])
            scores = []
            for gt_target, pred_track in zip(ground_truth, closest_tracks):
                is_close_enough = np.linalg.norm(pred_track.position-gt_target.position) < POSITION_ERROR_ACCEPTABLE_BOUND
                scores.append(int(is_close_enough))
                if i==0 and verbose:
                    print(f"Closest Match for {stringify_target_description(gt_target.description)}:")
                    physically_closest_match = min(predictions_3d, key=lambda pred: np.linalg.norm(pred.position-gt_target.position))
                    closest_match = max(predictions_3d, key=lambda pred: calc_match_score(pred.description, gt_target.description))
                    print(stringify_target_description(gt_target.description))

                    print(f"\tTrack distance: {np.linalg.norm(pred_track.position-gt_target.position):.3f}")
                    print(f"\tDetections used in track:")
                    print(f"\t\t{[detection.id for detection in pred_track.get_measurements()]}") 

                    print(f"\tClose tracks (each line is one track):")
                    for track in tracker.tracks:
                        if np.linalg.norm(track.position - gt_target.position) < POSITION_ERROR_ACCEPTABLE_BOUND:
                            print(f"\t\t{[detection.id for detection in track.get_measurements()]}")

                    print(f"\tClose detections:")
                    print(f"\t\t{[p.id for p in filter(lambda pred: np.linalg.norm(pred.position-gt_target.position) < POSITION_ERROR_ACCEPTABLE_BOUND, predictions_3d)]}")
                    print(f"\tPhysically closest detection distance: {np.linalg.norm(physically_closest_match.position-gt_target.position):.3f}")
                    print(f"\tPhysically closest detection descriptor score: {calc_match_score(physically_closest_match.description, gt_target.description)}")
                    print(f"\tPhysically closest detection id: {physically_closest_match.id}")
                    print(f"\tHighest descriptor match score: {calc_match_score(closest_match.description, gt_target.description)}")
                    print(f"\tHighest descriptor match id: {closest_match.id}")
                    print(f"\tHigh descriptor match distance: {np.linalg.norm(closest_match.position-gt_target.position):.3f}")
                    print(f"\tClose enough? {is_close_enough}")
            if i==0: 
                print(f"Imaging Sim Score: {np.sum(scores)}/{len(scores)}") 
            scores_across_subsets.append(np.sum(scores))
        print(f"Imaging Sim Average Score: {np.mean(scores_across_subsets)}/{len(scores)}")


if __name__ == "__main__":
    tests = TestPipeline()
    tests.test_with_sim_dataset()