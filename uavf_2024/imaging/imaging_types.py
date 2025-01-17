from __future__ import annotations
from dataclasses import dataclass
import os
from typing import Generator, Generic, NamedTuple, TypeVar, Union
import cv2
import numpy as np
from enum import Enum

import torch

COLOR_INDICES = {
    "red": 0,
    "orange": 1,
    "green": 2,
    "blue": 3,
    "purple": 4,
    "white": 5,
    "black": 6,
    "brown": 7,
}


SHAPES = [
 "circle",
 "semicircle",
 "quartercircle",
 "triangle",
 "rectangle",
 "pentagon",
 "star",
 "cross",
 "person"
]

# LETTERS_OLD = "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789"
# LETTERS_NEW = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# LETTERS is based on the letter order in letter model's raw_output[0].names
# it is basically LETTER_NEW in alphabetical order (0-35)
LETTERS = "01ABCDEFGHIJ2KLMNOPQRST3UVWXYZ456789"

COLORS = list(COLOR_INDICES.keys())

# TODO: Limit these to the types we actually use
integer = Union[int, np.uint8, np.uint16, np.uint32, np.uint64, np.int8, np.int16, np.int32, np.int64]
real = Union[float, np.float16, np.float32, np.float64]
number = Union[integer, real]

# Can't use np.uint16 because torch doesn't support it. We're good as long as we don't have a gigapixel camera.
img_coord_t = np.int16

NEWLINE = '\n' + ' '*16 # For use in f-strings because apparently you can't use escape characters in them

@dataclass
class ProbabilisticTargetDescriptor:
    shape_probs: np.ndarray
    letter_probs: np.ndarray
    shape_col_probs: np.ndarray
    letter_col_probs: np.ndarray
    def __repr__(self):
        return f'''
        TargetDescription(
            Shapes:
                {NEWLINE.join([f"{SHAPES[i]}: {self.shape_probs[i]:.{3}f}" for i in range(len(self.shape_probs))])}
            Letters:
                {NEWLINE.join([f"{LETTERS[i]}: {self.letter_probs[i]:.{3}f}" for i in range(len(self.letter_probs))])}
            Shape Colors:
                {NEWLINE.join([f"{COLORS[i]}: {self.shape_col_probs[i]:.{3}f}" for i in range(len(self.shape_col_probs))])}
            Letter Colors:
                {NEWLINE.join([f"{COLORS[i]}: {self.letter_col_probs[i]:.{3}f}" for i in range(len(self.letter_col_probs))])}
        )
        '''

    @staticmethod
    def from_string(string: str) -> ProbabilisticTargetDescriptor:
        '''
        Converts a string representation of a ProbabilisticTargetDescriptor back into a ProbabilisticTargetDescriptor object.
        '''
        shape_lines = string.split("Shapes:\n")[1].split("Letters:")[0].split("\n")[:-1]
        shape_probs = np.array([float(line.split(": ")[1].strip()) for line in shape_lines])
        letter_lines = string.split("Letters:\n")[1].split("Shape Colors:")[0].split("\n")[:-1]
        letter_probs = np.array([float(line.split(": ")[1].strip()) for line in letter_lines])
        shape_col_lines = string.split("Shape Colors:\n")[1].split("Letter Colors:")[0].split("\n")[:-1]
        shape_col_probs = np.array([float(line.split(": ")[1].strip()) for line in shape_col_lines])
        letter_col_lines = string.split("Letter Colors:\n")[1].split("\n")[:-2]
        letter_col_probs = np.array([float(line.split(": ")[1].strip()) for line in letter_col_lines])
        return ProbabilisticTargetDescriptor(shape_probs, letter_probs, shape_col_probs, letter_col_probs)

    def __add__(self, other):
        return ProbabilisticTargetDescriptor(
            self.shape_probs + other.shape_probs,
            self.letter_probs + other.letter_probs,
            self.shape_col_probs + other.shape_col_probs,
            self.letter_col_probs + other.letter_col_probs,
        )

    def __truediv__(self, scalar):
        return ProbabilisticTargetDescriptor(
            self.shape_probs / scalar,
            self.letter_probs / scalar,
            self.shape_col_probs / scalar,
            self.letter_col_probs / scalar
        )
    
    def collapse_to_certain(self) -> CertainTargetDescriptor:
        return CertainTargetDescriptor(
            COLORS[np.argmax(self.shape_col_probs)],
            SHAPES[np.argmax(self.shape_probs)],
            COLORS[np.argmax(self.letter_col_probs)],
            LETTERS[np.argmax(self.letter_probs)]
        )


class CertainTargetDescriptor:
    '''
    `shape` is one of "circle", "semicircle", "quartercircle", "triangle", "rectangle", "pentagon", "star", "cross", "person"
    `letter` is an uppercase letter or a number (e.g. "A" or "1")
    `shape_col` and `letter_col` are one of "red", "green", "blue", "orange", "purple", "white", "black", "brown"

    A `None` value should only be used for ground truth data that is missing labels, or the "person" shape, which doesn't have a color or letter.
    ''' 
    def __init__(self, shape_col: str, shape: str, letter_col: str, letter: str):
        assert shape is None or shape in SHAPES
        self.shape = shape
        # if shape == "person":
        #     self.shape_col = None
        #     self.letter_col = None
        #     self.letter = None
        #     return

        assert shape_col is None or shape_col in COLORS
        assert letter_col is None or letter_col in COLORS
        assert letter is None or letter in LETTERS
        self.shape_col = shape_col
        self.letter_col = letter_col
        self.letter = letter

    @staticmethod
    def from_indices(shape_index: int, letter_index: int, shape_col_index: int, letter_col_index: int) -> CertainTargetDescriptor:
        '''
        Using indices is unsafe because it's easy to mix them up. The __init__ constructor should be used whenever possible.
        '''
        return CertainTargetDescriptor(
            COLORS[shape_col_index],
            SHAPES[shape_index],
            COLORS[letter_col_index],
            LETTERS[letter_index]
        )

    def to_indices(self):
        '''
        Returns class indices in order (shape_col, shape, letter_col, letter)    

        If a value is None, it will be returned as None in the tuple instead of an integer.
        '''
        return (
            COLORS.index(self.shape_col) if self.shape_col is not None else None,
            SHAPES.index(self.shape) if self.shape is not None else None,
            COLORS.index(self.letter_col) if self.letter_col is not None else None,
            LETTERS.index(self.letter) if self.letter is not None else None
        )
    
    def as_probabilistic(self, force_through_none = True) -> ProbabilisticTargetDescriptor:
        '''
        If force_through_none is True, then the None values will be converted to a uniform distribution over the possible values.
        otherwise, an error will be raised if any of the values are None.
        '''
        err_message = '''Cannot convert to probabilistic if any of the values are None (probably trying 
                        to convert a ground truth label with missing data, which shouldn't be done'''

        if not force_through_none and None in [self.shape, self.letter, self.shape_col, self.letter_col]:
            raise ValueError(err_message+ f" {self}")

        shape_probs = np.zeros(len(SHAPES))
        shape_probs[SHAPES.index(self.shape)] = 1.0

        if self.letter is None:
            letter_probs = np.ones(len(LETTERS)) / len(LETTERS)
        else:
            letter_probs = np.zeros(len(LETTERS))
            letter_probs[LETTERS.index(self.letter)] = 1.0

        if self.shape_col is None:
            shape_col_probs = np.ones(len(COLORS)) / len(COLORS)
        else:
            shape_col_probs = np.zeros(len(COLORS))
            shape_col_probs[COLORS.index(self.shape_col)] = 1.0
        
        if self.letter_col is None:
            letter_col_probs = np.ones(len(COLORS)) / len(COLORS)
        else:
            letter_col_probs = np.zeros(len(COLORS))
            letter_col_probs[COLORS.index(self.letter_col)] = 1.0

        return ProbabilisticTargetDescriptor(shape_probs, letter_probs, shape_col_probs, letter_col_probs)

    def __repr__(self):
        return f"{self.shape_col} {self.shape} {self.letter_col} {self.letter}"

CertainTargetDescriptor.from_indices(0, 0, 0, 0)
@dataclass
class Tile:
    img: 'Image'
    x: img_coord_t
    y: img_coord_t

@dataclass
class BoundingBox:
    x: img_coord_t
    y: img_coord_t
    width: img_coord_t
    height: img_coord_t

    def to_ndarray(self):
        return np.array([self.x, self.y, self.width, self.height])

    def to_xyxy(self):
        return np.array([self.x-self.width//2, self.y-self.height//2, self.x+self.width//2, self.y+self.height//2])

    @staticmethod
    def from_ndarray(arr: np.ndarray):
        '''Takes ndarray of shape (4,) [x,y,width,height] and returns a BoundingBox object'''
        return BoundingBox(*arr)

@dataclass
class FullBBoxPrediction:
    x: img_coord_t
    y: img_coord_t
    width: img_coord_t
    height: img_coord_t
    '''
    We can worry about typechecking these later, but the gist is that they're probability distributions over the possible classes.
    '''
    descriptor: ProbabilisticTargetDescriptor
    '''
    The id is a unique identifier for debugging purposes. All the debugging images will be saved with this id.
    The format is `{run_id}_{image_id}_{prediction_index}`
    '''
    img_id: int = None
    det_id: int = None

@dataclass
class FullBBoxGroundTruth:
    x: img_coord_t
    y: img_coord_t
    width: img_coord_t
    height: img_coord_t
    descriptor: CertainTargetDescriptor
    img_id: int = None
    det_id: int = None

@dataclass
class DetectionResult:
    '''
    `mask` and `img` should be (w,h,c) where c is 1 for mask and 3 for img
    '''
    x: img_coord_t
    y: img_coord_t
    width: img_coord_t
    height: img_coord_t
    confidences: np.ndarray
    img: 'Image'
    id : int

@dataclass
class Target3D:
    '''
    Class to represent our estimate of a target's 3d position and labels as well as the confidence in those labels.

    We might also want to incorporate information about the distance from which we've seen this target. Like, if we've only seen it from far away, and we get a new classification from a closer image, it should have more weight.
    '''
    position: np.ndarray # (x,y,z) in local frame
    descriptor: ProbabilisticTargetDescriptor
    id: str = None
    @staticmethod
    def from_ros(msg: ROSDetectionMessage) -> Target3D:
        return Target3D(
            np.array([msg.x, msg.y, msg.z]),
            ProbabilisticTargetDescriptor(
                np.array(msg.shape_conf),
                np.array(msg.letter_conf),
                np.array(msg.shape_color_conf),
                np.array(msg.letter_color_conf)
            ),
            msg.id
        )
    def __repr__(self):
        certain = self.descriptor.collapse_to_certain()
        descriptor_str = f'{certain.shape_col} ({max(self.descriptor.shape_col_probs)}) {certain.shape} ({max(self.descriptor.shape_probs)}) {certain.letter_col} ({max(self.descriptor.letter_col_probs)}) {certain.letter} ({max(self.descriptor.letter_probs)})'
        position_str = f'({self.position[0]:.02f}, {self.position[1]:.02f}, {self.position[2]:.02f})'

        return f'{descriptor_str} at {position_str} with id {self.id}'

@dataclass
class ROSDetectionMessage:
    '''
    Dataclass that should have the same fields as msg/TargetDetection.msg,
    to make it easier to get type hints and convert between the message type
    and other types.
    '''
    timestamp: int
    x: float
    y: float
    z: float
    shape_conf: list[float]
    letter_conf: list[float]
    shape_color_conf: list[float]
    letter_color_conf: list[float]
    id: str

class ImageDimension(Enum):
    HEIGHT = 'h'
    WIDTH = 'w'
    CHANNELS = 'c'
    
HEIGHT = ImageDimension.HEIGHT
WIDTH = ImageDimension.WIDTH
CHANNELS = ImageDimension.CHANNELS
    
class ImageDimensionsOrder(NamedTuple):
    first_dim: ImageDimension
    second_dim: ImageDimension
    third_dim: ImageDimension

# Can support other dimension orders if necessary
HWC = ImageDimensionsOrder(HEIGHT, WIDTH, CHANNELS)
CHW = ImageDimensionsOrder(CHANNELS, HEIGHT, WIDTH)
_VALID_DIM_ORDERS = {HWC, CHW}

_UnderlyingImageT = TypeVar('_UnderlyingImageT', np.ndarray, torch.Tensor)
class Image(Generic[_UnderlyingImageT]):
    """
    Wraps a numpy array or torch tensor representing an image.
    Contains information about the dimension order of the underlying array, e.g., (height, width, channels) or (channels, height, width).
    
    Except for passing data to predictors, you should interface through it directly instead of accessing _array.
    NOTE: Add methods to interface with it if necessary.
    
    Args:
        array (np.ndarray | torch.Tensor): The underlying array
        dim_order (ImageDimensionsOrder): The dimension order of the underlying array
    
    Examples:
        image_hwc[np.ndarray] = Image(np.zeros((20, 20, 3)), HWC)

        image_chw[torch.Tensor] = Image(torch.zeros((3, 20, 20)), CHW)
    """    
    def __init__(
        self, 
        array: _UnderlyingImageT, 
        dim_order: ImageDimensionsOrder = HWC
    ):
        if not isinstance(array, np.ndarray) and not isinstance(array, torch.Tensor):
            raise TypeError(f"array must be a numpy array or torch tensor. Got {type(array)}")
        
        if len(array.shape) != 3:
            raise ValueError("array must have 3 axes, got shape " + str(array.shape))
        
        if dim_order not in _VALID_DIM_ORDERS:
            raise ValueError("dim_order must be one of " + str(_VALID_DIM_ORDERS))

        self._dim_order = dim_order
        
        channels_index = self._dim_order.index(CHANNELS)
        if array.shape[channels_index] != 3:
            raise ValueError("Image array must have 3 channels, got " + str(array[channels_index]))
        
        self._array: _UnderlyingImageT = array
        
    def __getitem__(self, key):
        return self._array[key]
    
    def __setitem__(self, key, value: Union[np.ndarray, torch.Tensor, 'Image', int, float, np.number, torch.NumberType]):
        if isinstance(value, Image):
            value = value._array
        
        # I'm not sure why this thrown a fit in VS Code, but it work. Trust.
        self._array[key] = value # type: ignore
    
    def __eq__(self, other: 'Image'):
        """
        Checks whether two images are equal, including whether they have the same dimension order.
        """
        return isinstance(other, Image) and self._dim_order == other._dim_order and (self._array == other._array).all()
    
    def __repr__(self):
        return f"Image({self._array}, {self._dim_order})"
    
    def __mul__(self, other: number | _UnderlyingImageT) -> 'Image':
        """
        Multiplies the underlying array by a scalar or another array/tensor.
        """
        return Image(self._array * other, self._dim_order)
    
    def get_array(self) -> _UnderlyingImageT:
        return self._array
    
    def make_sub_image(self, x_coord, y_coord, width, height) -> 'Image':
        """
        Does not copy the underlying array.
        """
        indicies = [slice(None)] * 3
        indicies[self._dim_order.index(HEIGHT)] = slice(y_coord, y_coord+height)
        indicies[self._dim_order.index(WIDTH)] = slice(x_coord, x_coord+width)
        
        return Image(self._array[tuple(indicies)], self._dim_order) 
    
    def make_tile(self, x_coord, y_coord, tile_size) -> Tile:
        """
        Does not copy the underlying array.
        """
        return Tile(self.make_sub_image(x_coord, y_coord, tile_size, tile_size), x_coord, y_coord)
    
    def as_tile(self) -> Tile:
        return Tile(self, 0, 0)
    
    @property
    def shape(self):
        return self._array.shape
    
    @property 
    def dim_order(self):
        return self._dim_order
    
    @property
    def height(self):
        return self._array.shape[self._dim_order.index(HEIGHT)]
    
    @property
    def width(self):
        return self._array.shape[self._dim_order.index(WIDTH)]
    
    @property
    def channels(self):
        return self._array.shape[self._dim_order.index(CHANNELS)]
    
    @staticmethod
    def from_file(
        fp: str, 
        dim_order: ImageDimensionsOrder = HWC, 
        array_type: type[np.ndarray | torch.Tensor] = np.ndarray, 
        dtype: type[integer] = np.uint8
    ) -> 'Image[np.ndarray] | Image[torch.Tensor]':
        """
        Reads an image from a file. Uses cv2.imread internally, so the image will be in BGR format.
        
        Args:
            fp (str): The file path
            dim_order (ImageDimensionsOrder, optional): The desired dimension order of the underlying array. Defaults to HWC, cv2's default.
            array_type (type[np.ndarray | torch.Tensor], optional): The type of the underlying array. Defaults to np.ndarray.
            dtype (type[integer], optional): The type of the underlying array's elements. Defaults to np.uint8.
        
        Returns:
            Image: The image
        """
        if array_type == np.ndarray:
            array = cv2.imread(fp).astype(dtype)
            img = Image(array, HWC)
            if dim_order != HWC:
                img.change_dim_order(dim_order)
            
            return img
        
        elif array_type == torch.Tensor:
            # Inherits np.ndarray's dtype
            array = torch.from_numpy(cv2.imread(fp).astype(dtype))
            img = Image(array, HWC)
            if dim_order != HWC:
                img.change_dim_order(dim_order)
            
            return img
        
        else:
            raise TypeError("array_type must be np.ndarray or torch.Tensor")
    
    def save(self, fp: os.PathLike | str) -> None:
        """
        Saves the image to a file. Uses cv2.imwrite internally.
        
        
        Args:
            fp (str): The file path
        """
        np_array = np.array(self._array)
        
        # Tranpose if necessary.
        if self._dim_order == CHW:
            np_array = np_array.transpose(1, 2, 0)
        
        cv2.imwrite(str(fp), np_array)
    
    def change_dim_order(self, target_dim_order: ImageDimensionsOrder) -> None:
        """
        Use transpose to change the order of the dimensions in-place. This does NOT copy the underlying array.
        Changes the dim_order accordingly.
        """
        transposition_indices = (
            self._dim_order.index(target_dim_order.first_dim),
            self._dim_order.index(target_dim_order.second_dim),
            self._dim_order.index(target_dim_order.third_dim)
        )
        
        if isinstance(self._array, np.ndarray):
            self._array = self._array.transpose(transposition_indices)
        elif isinstance(self._array, torch.Tensor):
            self._array = self._array.permute(transposition_indices)
        else:
            TypeError("Inner array must be a numpy array or torch tensor")
        
        self._dim_order = target_dim_order
        
    def generate_tiles(self, tile_size: int, min_overlap: int = 0) -> Generator[Tile, None, None]:
        """
        Split high resolution input image into number of fixed-dimension, squares tiles, 
        ensuring that each tile overlaps with its neighbors by at least `min_overlap` pixels.

        @read: https://stackoverflow.com/questions/58383814/how-to-divide-an-image-into-evenly-sized-overlapping-if-needed-tiles

        Args:
            tile_size (int): Width/height of each tile
            min_overlap (int, optional): Number of pixels that each tile overlaps with its neighbors. Defaults to 0.

        Yields:
            Generator[Tile, None, None]: Generator that yields each tile
        """
    
        img_height, img_width = self.height, self.width

        if tile_size > img_width or tile_size > img_height:
            raise ValueError("tile dimensions cannot be larger than origin dimensions")

        # Number of tiles in each dimension
        x_count = np.uint8(np.ceil(
            (img_width - min_overlap) / (tile_size - min_overlap)
        ))
        y_count = np.uint8(np.ceil(
            (img_height - min_overlap) / (tile_size - min_overlap)
        ))

        # Total remainders
        overflow_x = tile_size + (x_count - 1) * (tile_size - min_overlap) - img_width
        overflow_y = tile_size + (y_count - 1) * (tile_size - min_overlap) - img_height

        # Temporarily suppress divide-by-zero warnings
        np.seterr(divide='ignore', invalid='ignore')

        # Set up remainders per tile
        remaindersX = np.ones((x_count-1,), dtype=np.uint8) * img_coord_t(np.floor(overflow_x / (x_count-1)))
        remaindersY = np.ones((y_count-1,), dtype=np.uint8) * img_coord_t(np.floor(overflow_y / (y_count-1)))
        remaindersX[0:np.remainder(overflow_x, img_coord_t(x_count-1))] += 1
        remaindersY[0:np.remainder(overflow_y, img_coord_t(y_count-1))] += 1

        np.seterr(divide='warn', invalid='warn')
            
        y = img_coord_t(0)
        for vertical_index in range(y_count):
            x = img_coord_t(0)
            for horizontal_index in range(x_count):
                # Converting back to int because its expected downstream
                # All dimensions should be refactored to use unit16
                yield self.make_tile(x, y, tile_size)
                
                if horizontal_index < (x_count-1):
                    next_horizontal_overlap = min_overlap + remaindersX[horizontal_index]
                    x += tile_size - next_horizontal_overlap
                    
            if vertical_index < (y_count-1):
                next_vertical_overlap = min_overlap + remaindersY[vertical_index]
                y += tile_size - next_vertical_overlap
