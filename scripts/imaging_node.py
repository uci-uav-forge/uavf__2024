#!/usr/bin/env python3

from pathlib import Path
import rclpy
from rclpy.node import Node
from libuavf_2024.msg import TargetDetection
from libuavf_2024.srv import TakePicture,PointCam,ZoomCam,GetAttitude,ResetLogDir
from uavf_2024.imaging import Camera, ImageProcessor, Localizer
import numpy as np
from geometry_msgs.msg import PoseStamped, Point
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
import time
import cv2 as cv
import json
import os
import traceback

def log_exceptions(func):
    '''
    Decorator that can be applied to methods on any class that extends
    a ros `Node` to make them correctly log exceptions when run through
    a roslaunch file
    '''
    def wrapped_fn(self,*args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception:
            self.get_logger().error(traceback.format_exc())
    return wrapped_fn

import os
from queue import Queue
from pathlib import Path
import threading
import time
from typing import Any, Callable, Generic, NamedTuple, TypeVar
from collections import deque
import csv
from uuid import UUID

from scipy.spatial.transform import Rotation

from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from rclpy.node import Node

from geometry_msgs.msg import PoseStamped, Point


class PoseDatum(NamedTuple):
    """
    Our representation of the pose data from the Cube.
    """
    position: Point
    rotation: Rotation
    time_seconds: float


class _PoseBuffer:
    def __init__(self, capacity: int = 4):
        if capacity < 1:
            raise ValueError(f"Buffer capacity cannot be less than 1. Got {capacity}")
        self._capacity = capacity
        self._queue: deque[PoseDatum] = deque(maxlen=self.capacity)
        
        # Lock for the whole queue. 
        # Not necessary if only the front is popped because that is thread-safe. 
        self.lock = threading.Lock()
        
    @property
    def capacity(self):
        return self._capacity
    
    @property
    def count(self):
        return len(self._queue)
        
    def __bool__(self):
        return bool(self.count)
    
    def put(self, datum: PoseDatum):
        with self.lock:
            # If the queue is too long, it'll automatically discard 
            # the item at the other end.
            self._queue.append(datum)
        
    def get_fresh(self, offset: int = 0):
        """
        Gets the item at the freshness offset specified (if specified).
        Otherwise, get the freshest datum
        """
        if offset < 0:
            raise ValueError(f"Offset cannot be less than 0. Got {offset}")
        
        with self.lock:
            return self._queue[-(offset + 1)]
    
    def get_all(self) -> list[PoseDatum]:
        """
        Returns all items in the buffer in the order of freshest first.
        
        Can be useful if we want a more refined search.
        """
        with self.lock:
            return list(reversed(self._queue))
        

InputT = TypeVar("InputT")
class Subscriptions(Generic[InputT]):
    """
    Manages subscriptions in a thread-safe way.
    
    This class can be used in the future to subsume ROS' subscription
    functionality when we stay within Python.
    """
    def __init__(self):
        self._callbacks: dict[UUID, Callable[[InputT], Any]] = {}
        self.lock = threading.Lock()
    
    def add(self, callback: Callable[[InputT], Any]) -> Callable[[], None]:
        """
        Adds the callback to the collection of subscriptions to be called
        when there is a notification.
        
        Returns a function to unsubscribe.
        """
        subscription_id = UUID()
        
        with self.lock:
            def unsubscribe():
                del self._callbacks[subscription_id]
            
            self._callbacks[subscription_id] = callback
        
        return unsubscribe

    def notify(self, new_value: InputT):
        """
        Calls all of the callbacks with the new value.
        
        Locks so that subscriptions will have to wait after a round of notifications.
        """
        with self.lock:
            for callback in self._callbacks.values():
                callback(new_value)


class PoseProvider:
    """
    Logs and buffers the world position for reading.
    
    Provides a method to subscribe to changes as well.
    """ 
    def __init__(
        self, 
        logs_path: str | os.PathLike | Path | None = None, 
        buffer_size = 5
    ):
        """
        Parameters:
            logs_path: The parent directory to which to log.
            buffer_size: The number of world positions to keep in the buffer
                for offsetted access.
        """
        self.logs_path = Path(logs_path) if logs_path else None
        
        if self.logs_path:
            if not self.logs_path.exists():
                self.logs_path.mkdir(parents=True)
            elif not self.logs_path.is_dir():
                raise FileExistsError(f"{self.logs_path} exists but is not a directory")
        
        # daemon=True allows the thread to be terminated when the class instance is deleted.
        self._logger_thread = threading.Thread(target=self._log_task, daemon=True)
        self._logs_queue: Queue[PoseDatum] = Queue()
        
        self._buffer = _PoseBuffer(buffer_size)
        
        # This is encapsulated so as not to expose Node's interface
        # The type error is just from rclpy and is unavoidable
        self._world_pos_node = Node("world_pos_node") # type: ignore
        
        # Initialize Quality-of-Service profile for subscription
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            depth = 1
        )
        
        self._world_pos_node.create_subscription(
            PoseStamped,
            '/mavros/local_position/pose',
            self.handle_pose_update,
            qos_profile
        )
        
        self._subscribers: Subscriptions[PoseDatum] = Subscriptions()
        
    def handle_pose_update(self, pose: PoseStamped) -> None:
        quaternion = pose.pose.orientation
        formatted = PoseDatum(
            position = pose.pose.position,
            rotation = Rotation.from_quat(
                [quaternion.x, quaternion.y, quaternion.z, quaternion.w]),
            time_seconds = pose.header.stamp.sec + pose.header.stamp.nanosec / 1e9
        )
        self._buffer.put(formatted)
        self._subscribers.notify(formatted)
        
    def get(self, offset: int = 0):
        """
        Gets the item at the freshness offset specified (if specified).
        Otherwise, get the freshest datum
        """
        return self._buffer.get_fresh(offset)
    
    def _log_task(self):
        """
        Task to pull from the _logs_queue and write the pose to file.
        """
        if self.logs_path is None:
            return
        
        with open(self.logs_path / "poses.csv") as f:
            writer = csv.writer(f)
            writer.writerow(PoseDatum._fields)
            
            while True:
                datum = self._logs_queue.get()
                writer.writerow(datum)
    
    def subscribe(self, callback: Callable[[PoseDatum], Any]):
        self._subscribers.add(callback)
        
    def wait_for_pose(self, timeout_seconds: float = float('inf')):
        """
        Waits until the first pose is added to the buffer.
        """
        start = time.time()
        
        while self._buffer.count == 0:
            if time.time() - start >= timeout_seconds:
                raise TimeoutError("Timed out waiting for pose")
            
            time.sleep(0.1)

class ImagingNode(Node):
    @log_exceptions
    def __init__(self) -> None:
        # Initialize the node
        super().__init__('imaging_node') # type: ignore
        logs_path = Path(f'logs/{time.strftime("%m-%d %H:%M")}')
        
        self.camera = Camera(logs_path / "camera")
        self.zoom_level = 3
        self.camera_state = False # True if camera is pointing down for auto-cam-point. Only for auto-point FSM
        self.camera.setAbsoluteZoom(self.zoom_level)
        
        self.log(f"Logging to {logs_path}")
        self.image_processor = ImageProcessor(logs_path / "image_processor")

        # Set up ROS connections
        self.log(f"Setting up imaging node ROS connections")
        
        # Subscriptions ----
        self.pose_provider = PoseProvider(logs_path)
        self.pose_provider.subscribe(self.cam_auto_point)

        # Services ----
        # Set up take picture service
        self.imaging_service = self.create_service(TakePicture, 'imaging_service', self.get_image_down)
        # Set up recenter camera service
        self.recenter_service = self.create_service(PointCam, 'recenter_service', self.request_point_cb)
        # Set up zoom camera service
        self.zoom_service = self.create_service(ZoomCam, 'zoom_service', self.setAbsoluteZoom_cb)
        # Set up reset log directory service
        self.reset_log_dir_service = self.create_service(ResetLogDir, 'reset_log_dir', self.reset_log_dir_cb)

        # Cleanup
        self.get_logger().info("Finished initializing imaging node")
        
    
    @log_exceptions
    def log(self, *args, **kwargs):
        self.get_logger().info(*args, **kwargs)

    @log_exceptions
    def cam_auto_point(self, current_pose: PoseDatum):
        z = current_pose.position.z
        
        # If pointed down and close to the ground, point forward
        if(self.camera_state and z < 10): #10 meters ~ 30 feet
            self.camera.request_center()
            self.camera_state = False
            self.log(f"Crossing 10m down, pointing forward. Current position: {z}")
        # If pointed forward and altitude is higher, point down
        elif(not self.camera_state and z > 10):
            self.camera.request_down()
            self.camera_state = True
            self.log(f"Crossing 10m up, pointing down. Current position: {z}")
        else:
            return
        self.camera.request_autofocus()


    @log_exceptions
    def request_point_cb(self, request, response):
        self.log(f"Received Point Camera Down Request: {request}")
        if request.down:
            response.success = self.camera.request_down()
        else:
            response.success = self.camera.request_center()
        self.camera.request_autofocus()
        return response
    
    @log_exceptions
    def setAbsoluteZoom_cb(self, request, response):
        self.log(f"Received Set Zoom Request: {request}")
        response.success = self.camera.setAbsoluteZoom(request.zoom_level)
        self.camera.request_autofocus()
        self.zoom_level = request.zoom_level
        return response

    @log_exceptions
    def reset_log_dir_cb(self, request, response):
        new_logs_dir = Path('logs/{strftime("%m-%d %H:%M")}')
        self.log(f"Starting new log directory at {new_logs_dir}")
        os.makedirs(new_logs_dir, exist_ok = True)
        self.image_processor.reset_log_directory(new_logs_dir / 'image_processor')
        self.camera.set_log_dir(new_logs_dir / 'camera')
        response.success = True
        return response
    
    @log_exceptions
    def make_localizer(self):
        focal_len = self.camera.getFocalLength()
        localizer = Localizer.from_focal_length(
            focal_len, 
            (1920, 1080),
            (np.array([1,0,0]), np.array([0,-1, 0])),
            2    
        )
        return localizer

    @log_exceptions
    def point_camera_down(self):
        self.camera.request_down()
        while abs(self.camera.getAttitude()[1] - -90) > 2:
            self.log(f"Waiting to point down. Current angle: {self.camera.getAttitude()[1] } . " )
            time.sleep(0.1)
        self.log("Camera pointed down")
        self.camera.request_autofocus()

    @log_exceptions
    def get_image_down(self, request, response: list[TargetDetection]) -> list[TargetDetection]:
        '''
            autofocus, then wait till cam points down, take pic,
        
            We want to take photo when the attitude is down only. 
        '''
        self.log("Received Down Image Request")

        if abs(self.camera.getAttitude()[1] - -90) > 5: # Allow 5 degrees of error (Arbitrary)
            self.point_camera_down()

        #TODO: Figure out a way to detect when the gimbal is having an aneurism and figure out how to fix it or send msg to groundstation.
        
        # Take picture and grab relevant data
        localizer = self.make_localizer()
        start_angles = self.camera.getAttitude()
        img = self.camera.get_latest_image()
        timestamp = time.time()
        end_angles = self.camera.getAttitude()

        if img is None:
            self.log("Could not get image from Camera.")
            return []
    
        detections = self.image_processor.process_image(img)

        # Get avg camera pose for the image
        avg_angles = np.mean([start_angles, end_angles],axis=0) # yaw, pitch, roll
        
        self.pose_provider.wait_for_pose()
        pose = self.pose_provider.get()

        cur_position_np = np.array([pose.position.x, pose.position.y, pose.position.z])
        cur_rot_quat = pose.rotation.as_quat()

        world_orientation = self.camera.orientation_in_world_frame(pose.rotation, avg_angles)
        cam_pose = (cur_position_np, world_orientation)

        # Get 3D predictions
        preds_3d = [localizer.prediction_to_coords(d, cam_pose) for d in detections]

        # Log data
        logs_folder = self.image_processor.get_last_logs_path()
        self.log(f"This frame going to {logs_folder}")
        self.log(f"Zoom level: {self.zoom_level}")
        self.log(f"{len(detections)} detections \t({'*'*len(detections)})")
        os.makedirs(logs_folder, exist_ok=True)
        cv.imwrite(f"{logs_folder}/image.png", img.get_array())
        log_data = {
            'pose_time': pose.time_seconds,
            'image_time': timestamp,
            'drone_position': cur_position_np.tolist(),
            'drone_q': cur_rot_quat.tolist(),
            'gimbal_yaw': avg_angles[0],
            'gimbal_pitch': avg_angles[1],
            'gimbal_roll': avg_angles[2],
            'zoom level': self.zoom_level,
            'preds_3d': [
                {
                    'position': p.position.tolist(),
                    'id': p.id,
                } for p in preds_3d
            ]
        }
        json.dump(log_data, open(f"{logs_folder}/data.json", 'w+'), indent=4)

        response.detections = []
        for i, p in enumerate(preds_3d):
            t = TargetDetection(
                timestamp = int(timestamp*1000),
                x = p.position[0],
                y = p.position[1],
                z = p.position[2],
                shape_conf = p.descriptor.shape_probs.tolist(),
                letter_conf = p.descriptor.letter_probs.tolist(),
                shape_color_conf = p.descriptor.shape_col_probs.tolist(),
                letter_color_conf = p.descriptor.letter_col_probs.tolist(),
                id = p.id
            )

            response.detections.append(t)

        return response
        

def main(args=None) -> None:
    print('Starting imaging node...')
    rclpy.init(args=args)
    node = ImagingNode()
    rclpy.spin(node)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(e)
