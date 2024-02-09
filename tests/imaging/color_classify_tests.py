import unittest
from uavf_2024.imaging.color_classification import ColorClassifier, COLORS_TO_RGB
import numpy as np
import cv2 as cv
from PIL import Image
import numpy as np
import os
CURRENT_FILE_PATH = os.path.dirname(os.path.realpath(__file__))
class ColorClassificationTest(unittest.TestCase):
    def test_blue_color_classification(self):
        '''
        Test case for blue color classification. 
        This specific shade of blue was misclassified as purple
        when we first made the simple KNN color classifier with 1 example per color.
        '''
        image_path = CURRENT_FILE_PATH + '/imaging_data/fake_dataset/0.jpg'
        image = Image.open(image_path)
        classifier = ColorClassifier()
        shape_score, letter_score = classifier.predict(image)
        red = list(COLORS_TO_RGB.keys()).index('red')
        orange = list(COLORS_TO_RGB.keys()).index('orange')
        
        self.assertEqual(np.argmax(letter_score), red) 
        self.assertEqual(np.argmax(shape_score), orange) 

if __name__ == '__main__':
    unittest.main()