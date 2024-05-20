#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from libuavf_2024.msg import TargetDetection
from libuavf_2024.srv import TakePicture,GetAttitude
from uavf_2024.imaging import Camera, ImageProcessor, Localizer
from scipy.spatial.transform import Rotation as R
import numpy as np
from geometry_msgs.msg import PoseStamped, Point
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from time import strftime, time, sleep
import cv2 as cv

class ImagingNode(Node):
    def __init__(self) -> None:
        super().__init__('imaging_node')
        self.camera = Camera()
        self.camera.setAbsoluteZoom(1)
        self.image_processor = ImageProcessor(f'logs/{strftime("%m-%d %H:%M")}/image_processor')
        focal_len = self.camera.getFocalLength()
        self.localizer = Localizer.from_focal_length(focal_len, (1920, 1080))

        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            depth = 1
        )

        self.got_pose = False

        self.world_position_sub = self.create_subscription(
            PoseStamped,
            '/mavros/local_position/pose',
            self.got_pose_cb,
            qos_profile)

        self.imaging_service = self.create_service(TakePicture, 'imaging_service', self.get_image_down)
        self.get_logger().info("Finished initializing imaging node")
        
    def got_pose_cb(self, pose: PoseStamped):
        self.cur_pose = pose
        self.cur_position = pose.pose.position
        self.cur_rot = R.from_quat([pose.pose.orientation.x,pose.pose.orientation.y,pose.pose.orientation.z,pose.pose.orientation.w,])
        self.got_pose = True

    def log(self, *args, **kwargs):
        self.get_logger().info(*args, **kwargs)
    
    def get_image_down(self, request, response: list[TargetDetection]) -> list[TargetDetection]:
        '''
            autofocus, then wait till cam points down, take pic,
        
            We want to take photo when the attitude is down only. 
        '''
        self.log("Received Down Image Request")

        self.camera.request_autofocus()
        self.camera.request_down()
        while abs(self.camera.getAttitude()[1] - -90) > 2:

            self.log(f"Waiting to point down. Current angle: {self.camera.getAttitude()[1] } . " )
            sleep(0.1)
        sleep(1) # To let the autofocus finish
        
        start_angles = self.camera.getAttitude()
        img = self.camera.take_picture()
        timestamp = time()
        end_angles = self.camera.getAttitude()
        self.log("Picture taken")

        detections = self.image_processor.process_image(img)

        cv.imwrite(f"{self.image_processor.get_last_logs_path()}/image.png", img.get_array())
        self.log("Images processed")

        avg_angles = np.mean([start_angles, end_angles],axis=0) # yaw, pitch, roll
        if not self.got_pose:
            self.get_logger().error("No pose info from mavros. Hanging until we get pose")
            for _ in range(5):
                if self.got_pose:
                    break
                self.log("Waiting for pose")
            if not self.got_pose:
                return
            else:
                self.log("Got pose finally!")

        cur_position_np = np.array([self.cur_position.x, self.cur_position.y, self.cur_position.z])

        with open(f"{self.image_processor.get_last_logs_path()}/cam_angles.txt", "w") as f:
            f.write(f"{start_angles}\n")
            f.write(f"{end_angles}")
            drone_quat = self.cur_rot.as_quat()
            f.write(f"{[drone_quat[0], drone_quat[1], drone_quat[2], drone_quat[3]]}")

        world_orientation = self.camera.orientation_in_world_frame(self.cur_rot, avg_angles)
        cam_pose = (cur_position_np, world_orientation)

        self.log("Writing cam pose to file")
        with open(f"{self.image_processor.get_last_logs_path()}/cam_pose.txt", "w") as f:
            f.write(f"{cur_position_np[0]},{cur_position_np[1]},{cur_position_np[2]}\n")
            rot_quat = world_orientation.as_quat()
            f.write(f"{rot_quat[0]},{rot_quat[1]},{rot_quat[2]},{rot_quat[3]}\n")
        
        self.log(f"{len(detections)} detections")
        preds_3d = [self.localizer.prediction_to_coords(d, cam_pose) for d in detections]

        self.log("Localization finished")

        response.detections = []
        # for i, p in enumerate(preds_3d):
        #     t = TargetDetection(
        #         timestamp = int(timestamp*1000),
        #         x = p.position[0],
        #         y = p.position[1],
        #         z = p.position[2],
        #         shape_conf = p.descriptor.shape_probs.tolist(),
        #         letter_conf = p.descriptor.letter_probs.tolist(),
        #         shape_color_conf = p.descriptor.shape_col_probs.tolist(),
        #         letter_color_conf = p.descriptor.letter_col_probs.tolist(),
        #         id = p.id
        #     )

        #     response.detections.append(t)

        self.log("Returning Response")

        return response

        

def main(args=None) -> None:
    print('Starting imaging node...')
    rclpy.init(args=args)
    node = ImagingNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(e)