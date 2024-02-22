from __future__ import annotations
import shutil
import torch
from torchvision.ops import box_iou
import unittest
from uavf_2024.imaging.image_processor import ImageProcessor
from uavf_2024.imaging.imaging_types import HWC, FullPrediction, Image, TargetDescription, LETTERS
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

def calc_metrics(predictions: list[FullPrediction], ground_truth: list[FullPrediction], 
                 debug_img: np.ndarray, debug_path: str, debug_lab: int):
    '''debug_img should be receiving the image np array, img.get_array(), and visuals are provided of the bounding box'''
    true_positives = 0 # how many predictions were on top of a ground-truth box
    targets_detected = 0 # how many ground-truth boxes had at least 1 prediction on top of them
    shape_top_1_accuracies = []
    letter_top_1_accuracies = []
    letter_top_5_accuracies = []
    shape_color_top_1_accuracies = []
    letter_color_top_1_accuracies = []

    #letter_dict is from the letter model's raw_output[0].names
    #it is basically 0-35 in alphabetical order and maps the predicton results from the model to 
    #the new letter labels indicies 
    letter_dict = {0: '0', 1: '1', 10: '2', 11: '3', 12: '4', 13: '5', 14: '6', 15: '7', 16: '8', 17: '9', 18: '10', 19: '11', 2: '12', 20: '13', 21: '14', 22: '15', 23: '16', 24: '17', 25: '18', 26: '19', 27: '20', 28: '21', 29: '22', 3: '23', 30: '24', 31: '25', 32: '26', 33: '27', 34: '28', 35: '29', 4: '30', 5: '31', 6: '32', 7: '33', 8: '34', 9: '35'}
    #old truth letter labels = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    #new letter labels = "01ABCDEFGHIJ2KLMNOPQRST3UVWXYZ456789"
    #old to new:
    # A - Z (0-25): + 10
    #1 - 9 (26-34): -25 '''


    
    for truth in ground_truth:
        x,y = truth.x, truth.y
        w,h = truth.width, truth.height 
        true_box = np.array([[
            x,y,x+w,y+h
        ]])
        shape = np.argmax(truth.description.shape_probs)
        letter = np.argmax(truth.description.letter_probs)
        shape_col = np.argmax(truth.description.shape_col_probs)
        letter_col = np.argmax(truth.description.letter_col_probs)
        
        if debug_img is not None:
            x, y, x1, y1 = true_box.flatten()
            color = (0, 0, 255) 
            thickness = 2
            cv2.rectangle(debug_img, (x, y), (x1, y1), color, thickness) 
            cv2.putText(debug_img, "truth", (x,y), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,255), 2)

        this_target_was_detected = False
        for pred in predictions:
            pred_box = np.array([[
                pred.x,pred.y,pred.x+pred.width,pred.y+pred.height
            ]])

            if debug_img is not None:
                x, y, x1, y1 = pred_box.flatten()
                color = (0, 255, 0)  
                thickness = 2
                cv2.rectangle(debug_img, (x, y), (x1, y1), color, thickness)  
                cv2.putText(debug_img, "prediction", (x,y), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)

            iou = box_iou(torch.Tensor(true_box), torch.Tensor(pred_box))
            if iou>0.5:
                true_positives+=1
                this_target_was_detected = True
                shape_top_1_accuracies.append(int(shape == np.argmax(pred.description.shape_probs)))
                
                letter_top5_probs = np.argsort(pred.description.letter_probs)[-5:] # [top5, top4, top3, top2, top1]
                letter_top5_probs = [int(i) for i in letter_top5_probs]  # get letter prob names
                letter_top_5_accuracies.append(int(letter in letter_top5_probs))
                
                letter_top_1_accuracies.append(int(letter == int(letter_top5_probs[4])))                
                shape_color_top_1_accuracies.append(int(shape_col == np.argmax(pred.description.shape_col_probs)))
                letter_color_top_1_accuracies.append(int(letter_col == np.argmax(pred.description.letter_col_probs)))

        if this_target_was_detected:
            targets_detected+=1

    if debug_img is not None:
         local_debug_path = f"{debug_path}/img_{debug_lab}"
         os.makedirs(local_debug_path, exist_ok=True)
         cv2.imwrite(f"{local_debug_path}/bounding_boxes.png", debug_img)

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

def parse_dataset(imgs_path, labels_path) -> tuple[list[Image], list[list[FullPrediction]]]:
    '''
    ret_value[i] is the list of predictions for the ith image
    ret_value[i][j] is the jth prediction for the ith image
    '''
    letter_dict = {0: '0', 1: '1', 10: '2', 11: '3', 12: '4', 13: '5', 14: '6', 15: '7', 16: '8', 17: '9', 18: '10', 19: '11', 2: '12', 20: '13', 21: '14', 22: '15', 23: '16', 24: '17', 25: '18', 26: '19', 27: '20', 28: '21', 29: '22', 3: '23', 30: '24', 31: '25', 32: '26', 33: '27', 34: '28', 35: '29', 4: '30', 5: '31', 6: '32', 7: '33', 8: '34', 9: '35'}

    imgs: list[Image] = []
    labels = []
    for img_file_name in os.listdir(imgs_path):
        img = Image.from_file(f"{imgs_path}/{img_file_name}")
        ground_truth: list[FullPrediction] = []

        with open(f"{labels_path}/{img_file_name.split('.')[0]}.txt") as f:
            for line in f.readlines():
                label = line.split(' ')
                shape, letter, shape_col, letter_col = map(int, label[:4])
                '''the conversion from old letter to new letter is made '''               
                letter = int(letter_dict[letter])

                box = np.array([float(v) for v in label[4:]])
                box[[0,2]]*=img.shape[1]
                box[[1,3]]*=img.shape[0]
                box[[0,1]] -= box[[2,3]] # adjust xy to be top-left
                x,y,w,h = box.astype(int)

                ground_truth.append(FullPrediction(
                    x,y,w,h,
                    TargetDescription(
                        np.eye(9)[shape], np.eye(36)[letter], np.eye(8)[shape_col], np.eye(8)[letter_col]
                    )
                ))
        
        imgs.append(img)
        labels.append(ground_truth)
        
    return (imgs, labels)


def generate_letter_confusion_matrix( unit_test_letter_truth, unit_test_letter_pred):
    letter_labels = list(LETTERS)
    letter_truth = []
    letter_pred = []
    '''parse over each image from the unit test data'''
    for img_truth, img_pred in zip(unit_test_letter_truth, unit_test_letter_pred):
        '''parse over each truth object within the image '''
        for truth_val in img_truth:
            letter_truth.append(np.argmax(truth_val.description.letter_probs))
            x,y = truth_val.x, truth_val.y
            w,h = truth_val.width, truth_val.height 
            true_box = np.array([[x,y,x+w,y+h]])
            '''compare each truth to every possible prediction '''
            for pred in img_pred:
                pred_box = np.array([[
                pred.x,pred.y,pred.x+pred.width,pred.y+pred.height
                ]])
                iou = box_iou(torch.Tensor(true_box), torch.Tensor(pred_box))
                if iou>0.1:
                    letter_pred.append(int(np.argmax(pred.description.letter_probs)))
                
                
    letter_confusion_matrix = np.zeros((36,36))

    for actual, predict in zip (letter_truth, letter_pred):
        letter_confusion_matrix[actual, predict]+= 1

    conf_matrix_df = pd.DataFrame(letter_confusion_matrix, index=letter_labels, columns=letter_labels)
    conf_matrix_df.to_csv(f"{CURRENT_FILE_PATH}/imaging_data/visualizations/test_metrics/letter_confusion_matrix.csv")

class TestImagingFrontend(unittest.TestCase):

    @mem_profile
    def test_runs_without_crashing(self):
        image_processor = ImageProcessor()
        sample_input = Image.from_file(f"{CURRENT_FILE_PATH}/imaging_data/fullsize_dataset/images/1080p.png")
        res = image_processor.process_image(sample_input)

    @profiler
    def test_benchmark_fullsize_images(self):
        image_processor = ImageProcessor(
            shape_batch_size=20,
            letter_batch_size=30
        )
        sample_input = Image.from_file(f"{CURRENT_FILE_PATH}/imaging_data/fullsize_dataset/images/1080p.png")
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
    
    def test_metrics(self, debug_letter_confusion = False):

        debug_output_folder = f"{CURRENT_FILE_PATH}/imaging_data/visualizations/test_metrics"
        debug_folder_path = f"{CURRENT_FILE_PATH}/imaging_data/visualizations/test_bounding_box"

        if os.path.exists(debug_output_folder):
            shutil.rmtree(debug_output_folder)
        image_processor = ImageProcessor(debug_output_folder)
        imgs, labels = parse_dataset(f"{CURRENT_FILE_PATH}/imaging_data/tile_dataset/images", f"{CURRENT_FILE_PATH}/imaging_data/tile_dataset/labels")
        
        recalls = []
        precisions = []
        shape_top1s = []
        letter_top1s = []
        letter_top5s = []
        shape_color_top1s = []
        letter_color_top1s = []
        img_counter = 0
        '''Storing the predictions from pipeline for the confusion matrix evaluation '''
        if debug_letter_confusion:
            prediction_list = []

        for img, ground_truth in zip(imgs, labels):
            predictions = image_processor.process_image(img)
            if debug_letter_confusion:
                prediction_list.append(predictions)
            (
                recall,
                precision,
                shape_top1,
                letter_top1,
                letter_top5,
                shape_color_top1,
                letter_color_top1
            ) = calc_metrics(predictions, ground_truth, debug_img= None, debug_path= debug_folder_path, debug_lab = img_counter) 
            img_counter += 1

            for metric, aggregate in zip(
                [recall, precision, shape_top1, letter_top1, letter_top5, shape_color_top1, letter_color_top1],
                [recalls, precisions, shape_top1s, letter_top1s, letter_top5s, shape_color_top1s, letter_color_top1s]
            ):
                if not metric is None:
                    aggregate.append(metric)
            

        if debug_letter_confusion:
            generate_letter_confusion_matrix(unit_test_letter_pred= prediction_list, unit_test_letter_truth= labels)

        print(f"Recall: {np.mean(recalls)}")
        print(f"Precision: {np.mean(precisions)}")
        print(f"Shape top 1 acc: {np.mean(shape_top1s)}")
        print(f"Letter top 1 acc: {np.mean(letter_top1s)}")
        print(f"Letter top 5 acc: {np.mean(letter_top5s)}")
        print(f"Shape color top 1 acc: {np.mean(shape_color_top1s)}")
        print(f"Letter color top 1 acc: {np.mean(letter_color_top1s)}")


if __name__ == "__main__":
    unittest.main()