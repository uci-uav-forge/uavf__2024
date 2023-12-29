import std_msgs.msg
import mavros_msgs.msg
import mavros_msgs.srv
import rclpy
import rclpy.node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
import sensor_msgs.msg
import geometry_msgs.msg 
import uavf_2024.srv
from libuavf_2024.gnc.util import read_gps, convert_delta_gps_to_local_m, convert_local_m_to_delta_gps, calculate_turn_angles_deg, read_payload_list
from libuavf_2024.gnc.dropzone_planner import DropzonePlanner
from scipy.spatial.transform import Rotation as R

class CommanderNode(rclpy.node.Node):
    '''
    Manages subscriptions to ROS2 topics and services necessary for the main GNC node. 
    '''

    def __init__(self, args):
        super().__init__('uavf_commander_node')

        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            depth = 1)

        # for now this is broken - some problem with the docker image or ardupilot setup...
        # todo, fix
        self.global_pos_sub = self.create_subscription(
            sensor_msgs.msg.NavSatFix,
            'ap/geopose/filtered',
            self.global_pos_cb,
            qos_profile)
        self.got_pos = False

        self.arm_client = self.create_client(mavros_msgs.srv.CommandBool, 'mavros/cmd/arming')
        
        self.mode_client = self.create_client(mavros_msgs.srv.SetMode, 'mavros/set_mode')

        self.takeoff_client = self.create_client(mavros_msgs.srv.CommandTOL, 'mavros/cmd/takeoff')

        self.waypoints_client = self.create_client(mavros_msgs.srv.WaypointPush, 'mavros/mission/push')
        self.clear_mission_client = self.create_client(mavros_msgs.srv.WaypointClear, 'mavros/mission/clear')

        self.take_picture_client = self.create_client(uavf_2024.srv.TakePicture, 'uavf_2024/take_picture')

        self.got_pose = False
        self.world_position_sub = self.create_subscription(
            geometry_msgs.msg.PoseStamped,
            '/mavros/local_position/pose',
            self.got_pose_cb,
            qos_profile)

        self.got_global_pos = False
        self.global_position_sub = self.create_subscription(
            sensor_msgs.msg.NavSatFix,
            '/mavros/global_position/global',
            self.got_global_pos_cb,
            qos_profile)

        self.last_wp_seq = None
        self.reached_sub = self.create_subscription(
            mavros_msgs.msg.WaypointReached,
            'mavros/mission/reached',
            self.reached_cb,
            qos_profile)
        
        self.imaging_client = self.create_client(
            uavf_2024.srv.TakePicture,
            '/imaging_service')
        
        self.mission_wps = read_gps(args.mission_file)
        self.dropzone_bounds = read_gps(args.dropzone_file)
        self.payloads = read_payload_list(args.payload_list)

        self.dropzone_planner = DropzonePlanner(self, args.image_width_m, args.image_height_m)
        self.args = args

        self.call_imaging_at_wps = False
        self.imaging_futures = []

        self.turn_angle_limit = 170
    
    def log(self, *args, **kwargs):
        print(*args, **kwargs)
    
    def global_pos_cb(self, global_pos):
        self.got_pos = True
        self.last_pos = global_pos
    
    def reached_cb(self, reached):
        self.log("Reached waypoint", reached.wp_seq)
        self.last_wp_seq = reached.wp_seq

        if self.call_imaging_at_wps:
            self.imaging_futures.append(self.imaging_client.call_async(uavf_2024.srv.TakePicture.Request()))
    
    def got_pose_cb(self, pose):
        self.cur_pose = pose
        self.cur_rot = R.from_quat([pose.pose.orientation.x,pose.pose.orientation.y,pose.pose.orientation.z,pose.pose.orientation.w,]).as_rotvec()
        self.got_pose = True

    def got_global_pos_cb(self, pos):
        # Todo this feels messy - there should be a cleaner way to get home-pos through MAVROS.
        if not self.got_global_pos:
            self.home_global_pos = pos
            
            self.dropzone_bounds_mlocal = [convert_delta_gps_to_local_m((pos.latitude, pos.longitude), x) for x in self.dropzone_bounds]
            self.log("Dropzone bounds in local coords:", self.dropzone_bounds_mlocal)

            self.got_global_pos = True
    
    def local_to_gps(self, local):
        return convert_local_m_to_delta_gps((self.home_global_pos.latitude,self.home_global_pos.longitude) , local)
    
    def execute_waypoints(self, waypoints, yaws = None, use_spline = False):
        if yaws is None:
            yaws = [float('NaN')] * len(waypoints)

        self.last_wp_seq = None

        self.log("Pushing waypoints")

        self.clear_mission_client.call(mavros_msgs.srv.WaypointClear.Request())

        # coordinate zero is reserved for home? todo fix, this is hacky
        waypoints = [(0.0,0.0)] + waypoints
        yaws = [float('NaN')] + yaws

        waypoint_msgs = []
        
        if use_spline:
            start_pos = (self.home_global_pos.latitude, self.home_global_pos.longitude)
            end_pos = self.dropzone_bounds[0]
            turn_angles = calculate_turn_angles_deg([start_pos] + waypoints[1:] + [end_pos])
            self.log("Calculated turn angles:", turn_angles)

            # Add turn angle for home
            turn_angles = [0] + turn_angles
            for i in range(len(waypoints)):
                waypoint_msgs.append(mavros_msgs.msg.Waypoint(
                        frame = mavros_msgs.msg.Waypoint.FRAME_GLOBAL_REL_ALT,
                        command = mavros_msgs.msg.CommandCode.NAV_WAYPOINT if turn_angles[i] >= self.turn_angle_limit else mavros_msgs.msg.CommandCode.NAV_SPLINE_WAYPOINT,
                        is_current = True,
                        autocontinue = True,

                        param1 = 0.0,
                        param2 = 5.0,
                        param3 = 0.0,
                        param4 = yaws[0] if turn_angles[i] >= self.turn_angle_limit else 0.0,

                        x_lat = waypoints[i][0],
                        y_long = waypoints[i][1],
                        z_alt = 0.0))
        else:
            waypoint_msgs = [
                    mavros_msgs.msg.Waypoint(
                        frame = mavros_msgs.msg.Waypoint.FRAME_GLOBAL_REL_ALT,
                        command = mavros_msgs.msg.CommandCode.NAV_WAYPOINT,
                        is_current = True,
                        autocontinue = True,

                        param1 = 0.0,
                        param2 = 5.0,
                        param3 = 0.0,
                        param4 = yaw,

                        x_lat = wp[0],
                        y_long = wp[1],
                        z_alt = 0.0)

                    for wp,yaw in zip(waypoints,yaws)]

        resp = self.waypoints_client.call(mavros_msgs.srv.WaypointPush.Request(start_index = 0, waypoints = waypoint_msgs))

        self.log("Pushed waypoints, setting mode.")

        # kludgy but works

        self.mode_client.call(mavros_msgs.srv.SetMode.Request( \
            base_mode = 0,
            custom_mode = 'GUIDED'))

        self.mode_client.call(mavros_msgs.srv.SetMode.Request( \
            base_mode = 0,
            custom_mode = 'AUTO'))

        self.log("Waiting for mission to finish.")

        while self.last_wp_seq != len(waypoints)-1:
            pass
    
    def release_payload(self):
        # mocked out for now.
        self.log("WOULD RELEASE PAYLOAD")
    
    def gather_imaging_detections(self):
        detections = []
        for future in self.imaging_futures:
            while not future.done():
                pass
            detections += future.result().detections
        self.imaging_futures = []
        return detections
    
    def wait_for_takeoff(self):
        '''
        Will be executed before the start of each lap. Will wait for a signal
        indicating that the drone has taken off and is ready to fly the next lap.
        '''
        self.log('Waiting for takeoff')

    def execute_mission_loop(self):
        while not self.got_global_pos:
            pass

        for lap in range(len(self.payloads)):
            self.log('Lap', lap)

            # Wait for takeoff
            self.wait_for_takeoff()

            # Fly waypoint lap
            self.execute_waypoints(self.mission_wps, use_spline=True)

            # Fly to drop zone and release current payload
            self.dropzone_planner.conduct_air_drop()

            # Fly back to home position
            self.execute_waypoints([(self.home_global_pos.latitude, self.home_global_pos.longitude)])