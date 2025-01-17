from __future__ import annotations
import shutil
import torch
from torchvision.ops import box_iou
import unittest
from uavf_2024.imaging.image_processor import ImageProcessor
from uavf_2024.imaging.imaging_types import HWC, FullBBoxPrediction, FullBBoxGroundTruth, Image, CertainTargetDescriptor, LETTERS, SHAPES, COLORS
from uavf_2024.imaging import profiler
import numpy as np
import os
from time import time
from tqdm import tqdm
import line_profiler
from memory_profiler import profile as mem_profile
import pandas as pd
import sys
import cv2 #for debugging purposes

CURRENT_FILE_PATH = os.path.dirname(os.path.realpath(__file__))


def calc_metrics(predictions: list[FullBBoxPrediction], ground_truth: list[FullBBoxGroundTruth], 
                 debug_img: np.ndarray, debug_path: str, img_num: int):
    #debug_img should be receiving the image np array, img.get_array(), and visuals are provided of the bounding box'''
    true_positives = 0 # how many predictions were on top of a ground-truth box
    targets_detected = 0 # how many ground-truth boxes had at least 1 prediction on top of them
    shape_top_1_accuracies = []
    letter_top_1_accuracies = []
    letter_top_5_accuracies = []
    shape_color_top_1_accuracies = []
    letter_color_top_1_accuracies = []

    for truth in ground_truth:
        x,y = truth.x, truth.y
        w,h = truth.width, truth.height 
        true_box = np.array([[
            x,y,x+w,y+h
        ]])
        
        shape_col, shape, letter_col, letter = truth.descriptor.to_indices()
       
        if debug_img is not None:
            x, y, x1, y1 = true_box.flatten()
            color = (0, 0, 255) 
            thickness = 2
            cv2.rectangle(debug_img, (x, y), (x1, y1), color, thickness) 

        this_target_was_detected = False
        for pred in predictions:
            pred_box = np.array([[
                pred.x-pred.width//2,pred.y-pred.height//2,pred.x+pred.width//2,pred.y+pred.height//2
            ]])

            iou = box_iou(torch.Tensor(true_box), torch.Tensor(pred_box))
            if iou>0.5:
                true_positives+=1
                this_target_was_detected = True
                if shape is not None:
                    shape_top_1_accuracies.append(int(shape == np.argmax(pred.descriptor.shape_probs)))
                
                if letter is not None:
                    letter_top5_probs = np.argsort(pred.descriptor.letter_probs)[-5:] # [top5, top4, top3, top2, top1]
                    letter_top5_probs = [int(i) for i in letter_top5_probs]  # get letter prob names
                    letter_top_5_accuracies.append(int(letter in letter_top5_probs))
                    
                    letter_top_1_accuracies.append(int(letter == int(letter_top5_probs[4])))                

                if shape_col is not None:
                    shape_color_top_1_accuracies.append(int(shape_col == np.argmax(pred.descriptor.shape_col_probs)))
                
                if letter_col is not None:
                    letter_color_top_1_accuracies.append(int(letter_col == np.argmax(pred.descriptor.letter_col_probs)))

        if this_target_was_detected:
            targets_detected+=1

    if debug_img is not None:
         local_debug_path = f"{debug_path}/img_{img_num}"
         os.makedirs(local_debug_path, exist_ok=True)
         cv2.imwrite(f"{local_debug_path}/ground_truth_bboxes.png", debug_img)

    recall = targets_detected / len(ground_truth) if len(ground_truth)>0 else None
    precision = true_positives / len(predictions) if len(predictions)>0 else None
    shape_top1 = np.mean(shape_top_1_accuracies) if len(shape_top_1_accuracies)>0 else None
    letter_top1 = np.mean(letter_top_1_accuracies) if len(letter_top_1_accuracies)>0 else None
    letter_top5 = np.mean(letter_top_5_accuracies) if len(letter_top_5_accuracies)>0 else None
    shape_color_top1 = np.mean(shape_color_top_1_accuracies) if len(shape_color_top_1_accuracies)>0 else None
    letter_color_top1 = np.mean(letter_color_top_1_accuracies) if len(letter_color_top_1_accuracies)>0 else None

    return (
        recall,
        precision,
        shape_top1,
        letter_top1,
        letter_top5,
        shape_color_top1,
        letter_color_top1
    )

def parse_dataset(imgs_path, labels_path) -> tuple[list[Image], list[list[FullBBoxGroundTruth]]]:

    #ret_value[i] is the list of predictions for the ith image
    #ret_value[i][j] is the jth prediction for the ith image

    letter_dict = {0: '0', 1: '1', 10: '2', 11: '3', 12: '4', 13: '5', 14: '6', 15: '7', 16: '8', 17: '9', 18: '10', 19: '11', 2: '12', 20: '13', 21: '14', 22: '15', 23: '16', 24: '17', 25: '18', 26: '19', 27: '20', 28: '21', 29: '22', 3: '23', 30: '24', 31: '25', 32: '26', 33: '27', 34: '28', 35: '29', 4: '30', 5: '31', 6: '32', 7: '33', 8: '34', 9: '35'}

    imgs: list[Image] = []
    labels = []
    for img_file_name in os.listdir(imgs_path):
        img = Image.from_file(f"{imgs_path}/{img_file_name}")
        ground_truth: list[FullBBoxGroundTruth] = []
        with open(f"{labels_path}/{img_file_name.split('.')[0]}.txt") as f:
            for line in f.readlines():
                label = line.split(' ')
                shape, letter, shape_col, letter_col = map(int, label[:4])
                #the conversion from old letter to new letter is made               
                letter = int(letter_dict[letter])

                box = np.array([float(v) for v in label[4:]])
                box[[0,2]]*=img.shape[1]
                box[[1,3]]*=img.shape[0]
                box[[0,1]] -= box[[2,3]] # adjust xy to be top-left
                x,y,w,h = box.astype(int)

                ground_truth.append(FullBBoxGroundTruth(
                    x,y,w,h,
                    CertainTargetDescriptor.from_indices(
                        shape, letter, shape_col, letter_col
                    )
                ))
        
        imgs.append(img)
        labels.append(ground_truth)
        
    return (imgs, labels)

def parse_str_dataset(imgs_path, labels_path) -> tuple[list[Image], list[list[FullBBoxGroundTruth]]]:
    imgs: list[Image] = []
    labels = []
    for img_file_name in os.listdir(imgs_path):
        img = Image.from_file(f"{imgs_path}/{img_file_name}")
        ground_truth: list[FullBBoxGroundTruth] = []
        with open(f"{labels_path}/{img_file_name.split('.')[0]}.txt") as f:
            for line in f.readlines():
                label, *bbox_strs = line.split(' ')
                if label == "person":
                    shape = "person"
                    letter = "idk"
                    shape_col = "idk"
                    letter_col = "idk"
                else:
                    shape_col, shape, letter_col, letter = label.split(',')

                if shape == "idk":
                    shape = None
                if letter == "idk":
                    letter = None
                if shape_col == "idk":
                    shape_col = None
                if letter_col == "idk":
                    letter_col = None

                box = np.array([float(v) for v in bbox_strs])
                box[[0,2]]*=img.shape[1]
                box[[1,3]]*=img.shape[0]
                box[[0,1]] -= box[[2,3]]/2 # adjust xy to be top-left
                x,y,w,h = box.astype(int)

                ground_truth.append(FullBBoxGroundTruth(
                    x,y,w,h,
                    CertainTargetDescriptor(
                        shape_col, shape, letter_col, letter
                    )
                ))
        
        imgs.append(img)
        labels.append(ground_truth)
        
    return (imgs, labels)   


def generate_confusion_matrices(true_values: list[list[FullBBoxGroundTruth]], pred_values: list[list[FullBBoxPrediction]], out_folder: str) -> None:
    shape_confusion = np.zeros((len(SHAPES), len(SHAPES)))
    letter_confusion = np.zeros((len(LETTERS), len(LETTERS)))
    shape_col_confusion = np.zeros((len(COLORS), len(COLORS)))
    letter_col_confusion = np.zeros((len(COLORS), len(COLORS)))

    #parse over each image from the unit test data
    for img_truth, img_pred in zip(true_values, pred_values):
        #parse over each truth object within the image 
        for true_box_pred in img_truth:
            x,y = true_box_pred.x, true_box_pred.y
            w,h = true_box_pred.width, true_box_pred.height 
            true_box = np.array([[x,y,x+w,y+h]])
            true_desc = true_box_pred.descriptor

            #compare each truth to every possible prediction
            for pred in img_pred:
                pred_box = np.array([[
                pred.x,pred.y,pred.x+pred.width,pred.y+pred.height
                ]])
                iou = box_iou(torch.Tensor(true_box), torch.Tensor(pred_box))
                if iou>0.1:
                    pred_shape_col, pred_shape, pred_letter_col, pred_letter = pred.descriptor.collapse_to_certain().to_indices()
                    shape_col, shape, letter_col, letter = true_desc.to_indices()
                    if shape is not None:
                        shape_confusion[shape, pred_shape_col]+=1
                    if letter is not None:
                        letter_confusion[letter, pred_letter]+=1
                    if shape_col is not None:
                        shape_col_confusion[shape_col, pred_shape_col]+=1
                    if letter_col is not None:
                        letter_col_confusion[letter_col, pred_letter_col]+=1
                    
                
    for name, confusion_matrix, index in zip(
        ["shape", "letter", "shape_col", "letter_col"],
        [shape_confusion, letter_confusion, shape_col_confusion, letter_col_confusion],
        [SHAPES, LETTERS, COLORS, COLORS]
    ):
        for i in range(len(index)):
            if confusion_matrix[i,i] < max(confusion_matrix[i]):
                print(f"WARNING: {name} confusion matrix is not diagonal dominant (potential label mismatch)")
                break
        conf_matrix_df = pd.DataFrame(confusion_matrix, index=list(index), columns=list(index))
        conf_matrix_df.to_csv(f"{out_folder}/{name}_confusion_matrix.csv")

class TestImagingFrontend(unittest.TestCase):

    @mem_profile
    def test_runs_without_crashing(self):
        image_processor = ImageProcessor()
        sample_input = Image.from_file(f"{CURRENT_FILE_PATH}/2024_test_data/fullsize_dataset/images/1080p.png")
        res = image_processor.process_image(sample_input)
        res2 = image_processor.process_image_lightweight(sample_input)

    @profiler
    def test_benchmark_fullsize_images(self):
        image_processor = ImageProcessor(
            shape_batch_size=20,
            letter_batch_size=30
        )
        sample_input = Image.from_file(f"{CURRENT_FILE_PATH}/2024_test_data/fullsize_dataset/images/1080p.png")
        times = []
        N_runs = 10
        for i in tqdm(range(N_runs)):
            start = time()
            res = image_processor.process_image(sample_input)
            elapsed = time()-start
            times.append(elapsed)
        print(f"Fullsize image benchmarks (average of {N_runs} runs):")
        print(f"Avg: {np.mean(times)}, StdDev: {np.std(times)}")
        # lstats = profiler.get_stats()
        # line_profiler.show_text(lstats.timings, lstats.unit)
    
    def test_metrics(self, gen_confusion_matrices = True):
        print("\nSynthetic dataset metrics:\n")
        debug_output_folder = f"{CURRENT_FILE_PATH}/visualizations/test_metrics"
        debug_folder_path = f"{CURRENT_FILE_PATH}/visualizations/test_bounding_box"

        if os.path.exists(debug_output_folder):
            shutil.rmtree(debug_output_folder)
        image_processor = ImageProcessor(debug_output_folder)
        imgs, labels = parse_dataset(f"{CURRENT_FILE_PATH}/2024_test_data/tile_dataset/images", f"{CURRENT_FILE_PATH}/2024_test_data/tile_dataset/labels")
        
        recalls = []
        precisions = []
        shape_top1s = []
        letter_top1s = []
        letter_top5s = []
        shape_color_top1s = []
        letter_color_top1s = []
        img_counter = 0
        
        #Storing the predictions from pipeline for the confusion matrix evaluation
        if gen_confusion_matrices:
            prediction_list = []

        for img, ground_truth in zip(imgs, labels):
            predictions = image_processor.process_image(img)
            

            if gen_confusion_matrices:
                prediction_list.append(predictions)
            (
                recall,
                precision,
                shape_top1,
                letter_top1,
                letter_top5,
                shape_color_top1,
                letter_color_top1
            ) = calc_metrics(predictions, ground_truth, debug_img= None, debug_path= debug_folder_path, img_num= img_counter) 
            img_counter += 1

            for metric, aggregate in zip(
                [recall, precision, shape_top1, letter_top1, letter_top5, shape_color_top1, letter_color_top1],
                [recalls, precisions, shape_top1s, letter_top1s, letter_top5s, shape_color_top1s, letter_color_top1s]
            ):
                if not metric is None:
                    aggregate.append(metric)
            
        out_folder = f"{CURRENT_FILE_PATH}/visualizations/test_metrics"
        if gen_confusion_matrices:
            generate_confusion_matrices(labels, prediction_list, out_folder)

        print(f"Recall: {np.mean(recalls)}")
        print(f"Precision: {np.mean(precisions)}")
        print(f"Shape top 1 acc: {np.mean(shape_top1s)}")
        print(f"Letter top 1 acc: {np.mean(letter_top1s)}")
        print(f"Letter top 5 acc: {np.mean(letter_top5s)}")
        print(f"Shape color top 1 acc: {np.mean(shape_color_top1s)}")
        print(f"Letter color top 1 acc: {np.mean(letter_color_top1s)}")

    # TODO: replace shitty kwargs forwarding
    def test_irl_dataset(self, gen_confusion_matrices = True, verbose=True, **kwargs):
        debug_output_folder = f"{CURRENT_FILE_PATH}/visualizations/test_irl"

        if os.path.exists(debug_output_folder):
            shutil.rmtree(debug_output_folder)
        image_processor = ImageProcessor(debug_output_folder, **kwargs)
        imgs, labels = parse_str_dataset(f"{CURRENT_FILE_PATH}/2024_test_data/irl_dataset/images", f"{CURRENT_FILE_PATH}/2024_test_data/irl_dataset/labels")
        
        recalls = []
        precisions = []
        shape_top1s = []
        letter_top1s = []
        letter_top5s = []
        shape_color_top1s = []
        letter_color_top1s = []
        img_counter = 0
        
        #Storing the predictions from pipeline for the confusion matrix evaluation
        if gen_confusion_matrices:
            prediction_list = []

        for img, ground_truth in zip(imgs, labels):
            predictions = image_processor.process_image(img)
            

            if gen_confusion_matrices:
                prediction_list.append(predictions)
            (
                recall,
                precision,
                shape_top1,
                letter_top1,
                letter_top5,
                shape_color_top1,
                letter_color_top1
            ) = calc_metrics(predictions, ground_truth, debug_img= img.get_array(), debug_path= debug_output_folder, img_num= img_counter) 
            img_counter += 1

            for metric, aggregate in zip(
                [recall, precision, shape_top1, letter_top1, letter_top5, shape_color_top1, letter_color_top1],
                [recalls, precisions, shape_top1s, letter_top1s, letter_top5s, shape_color_top1s, letter_color_top1s]
            ):
                if not metric is None:
                    aggregate.append(metric)
            

        out_folder = f"{CURRENT_FILE_PATH}/visualizations/test_irl"
        if gen_confusion_matrices:
            generate_confusion_matrices(labels, prediction_list, out_folder)

        if verbose:
            print("\nIRL data metrics:\n")
            print(f"Recall: {np.mean(recalls)}")
            print(f"Precision: {np.mean(precisions)}")
            print(f"Shape top 1 acc: {np.mean(shape_top1s)}")
            print(f"Letter top 1 acc: {np.mean(letter_top1s)}")
            print(f"Letter top 5 acc: {np.mean(letter_top5s)}")
            print(f"Shape color top 1 acc: {np.mean(shape_color_top1s)}")
            print(f"Letter color top 1 acc: {np.mean(letter_color_top1s)}")

        return (np.mean(recalls), np.mean(precisions))
    
    def test_lightweight_process_one_image(self):
        # run lightweight
        # assert there is 1 instance 
        # assert the result is list[fullbboxpred]
        pass

    def test_lightweight_process_many(self):
        # run lightweight assert there is multiple instances
        # assert the result is a list[fullbboxpred] and has numbers in prob_descriptors
        image_processor = ImageProcessor()
        sample_input = Image.from_file(f"{CURRENT_FILE_PATH}/2024_test_data/fullsize_dataset/images/1080p.png")
        res = image_processor.process_image_lightweight(sample_input)
        
        assert type(res) is list
        assert type(res[0]) is FullBBoxPrediction
        if len(res) > 1:
            assert np.any(res[0].descriptor.letter_probs) and np.any(res[0].descriptor.shape_col_probs)





if __name__ == "__main__":
    tester = TestImagingFrontend()
    for tile_size in [1080]:
        for overlap in [0]:
            for conf in [0.01, 0.05, 0.1, 0.2, 0.25]:
                print(conf, tile_size, overlap)
                print(tester.test_irl_dataset(
                    False, 
                    False, 
                    tile_size=tile_size, 
                    min_tile_overlap=overlap,
                    conf=conf
                ))
