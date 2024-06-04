import std_msgs.msg
import mavros_msgs.msg
import mavros_msgs.srv
import rclpy
import rclpy.node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
import sensor_msgs.msg
import geometry_msgs.msg 
import libuavf_2024.srv
from uavf_2024.gnc.util import read_gps, convert_delta_gps_to_local_m, convert_local_m_to_delta_gps, \
    calculate_turn_angles_deg, read_payload_list, read_geofence, is_point_within_fence
from uavf_2024.gnc.dropzone_planner import DropzonePlanner
from scipy.spatial.transform import Rotation as R
import time

class CommanderNode(rclpy.node.Node):
    '''
    Manages subscriptions to ROS2 topics and services necessary for the main GNC node. 
    '''

    def __init__(self, args):
        super().__init__('uavf_commander_node')

        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            depth = 1
        )
        self.got_pos = False

        self.arm_client = self.create_client(mavros_msgs.srv.CommandBool, 'mavros/cmd/arming')
        
        self.mode_client = self.create_client(mavros_msgs.srv.SetMode, 'mavros/set_mode')

        self.takeoff_client = self.create_client(mavros_msgs.srv.CommandTOL, 'mavros/cmd/takeoff')

        self.waypoints_client = self.create_client(mavros_msgs.srv.WaypointPush, 'mavros/mission/push')
        self.clear_mission_client = self.create_client(mavros_msgs.srv.WaypointClear, 'mavros/mission/clear')

        self.land_client = self.create_client(mavros_msgs.srv.CommandTOL, 'mavros/cmd/land')

        self.cur_state = None
        self.state_sub = self.create_subscription(
            mavros_msgs.msg.State,
            'mavros/state',
            self.got_state_cb,
            qos_profile)

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

        self.last_wp_seq = -1
        self.reached_sub = self.create_subscription(
            mavros_msgs.msg.WaypointReached,
            'mavros/mission/reached',
            self.reached_cb,
            qos_profile)
        
        self.imaging_client = self.create_client(
            libuavf_2024.srv.TakePicture,
            '/imaging_service')

        # self.geofence = read_geofence(args.geofence_points)
        # self.mission_wps = read_gps(args.mission_file, self.geofence)
        # self.dropzone_bounds = read_gps(args.dropzone_file, self.geofence)
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
    
    def got_state_cb(self, state):
        self.cur_state = state
        # state.mode; if else -> quit
    
    def reached_cb(self, reached):
        if reached.wp_seq > self.last_wp_seq:
            self.log("Reached waypoint ", reached.wp_seq)
            self.last_wp_seq = reached.wp_seq

            if self.call_imaging_at_wps:
                self.imaging_futures.append(self.imaging_client.call_async(libuavf_2024.srv.TakePicture.Request()))
    
    def got_pose_cb(self, pose):
        self.cur_pose = pose
        self.cur_rot = R.from_quat([pose.pose.orientation.x,pose.pose.orientation.y,pose.pose.orientation.z,pose.pose.orientation.w,]).as_rotvec()
        self.got_pose = True

    def got_global_pos_cb(self, pos):
        #Todo this feels messy - there should be a cleaner way to get home-pos through MAVROS.
        self.last_global_pos = pos
        if not self.got_global_pos:
            self.home_global_pos = pos
            print(self.home_global_pos)
            
            self.dropzone_bounds_mlocal = [convert_delta_gps_to_local_m((pos.latitude, pos.longitude), x) for x in self.dropzone_bounds]
            self.log("Dropzone bounds in local coords:", self.dropzone_bounds_mlocal)

            self.got_global_pos = True
    
    def local_to_gps(self, local):
        return convert_local_m_to_delta_gps((self.home_global_pos.latitude,self.home_global_pos.longitude) , local)

    def execute_waypoints(self, waypoints, yaws = None):
        if yaws is None:
            yaws = [float('NaN')] * len(waypoints)

        self.last_wp_seq = -1

        self.log("Pushing waypoints")


        waypoints = [(self.last_global_pos.latitude, self.last_global_pos.longitude)] +  waypoints

        # # Validates that the waypoints are within the geofence
        # for waypoint in waypoints:
        #     assert is_point_within_fence(waypoint, self.geofence), "ERROR: Waypoint is not within the geofence"

        yaws = [float('NaN')] + yaws
        self.log(waypoints, yaws)
        

        waypoint_msgs = [
                mavros_msgs.msg.Waypoint(
                    frame = mavros_msgs.msg.Waypoint.FRAME_GLOBAL_REL_ALT,
                    command = mavros_msgs.msg.CommandCode.NAV_WAYPOINT,
                    is_current = False,
                    autocontinue = True,

                    param1 = 0.0,
                    param2 = 5.0,
                    param3 = 0.0,
                    param4 = yaw,

                    x_lat = wp[0],
                    y_long = wp[1],
                    z_alt = 20.0)

                for wp,yaw in zip(waypoints, yaws)]

        
        self.clear_mission_client.call(mavros_msgs.srv.WaypointClear.Request())

        self.log("Pushed waypoints, setting mode.")

        
        self.waypoints_client.call(mavros_msgs.srv.WaypointPush.Request(start_index = 0, waypoints = waypoint_msgs))
        # mavros/px4 doesn't consistently set the mode the first time this function is called...
        # retry or fail the script.
        for _ in range(1000):
            self.mode_client.call(mavros_msgs.srv.SetMode.Request( \
                base_mode = 0,
                custom_mode = 'AUTO.MISSION'
            ))
            time.sleep(0.2)
            if self.cur_state != None and self.cur_state.mode == 'AUTO.MISSION':
                self.log("Success setting mode")
                break
        else:
            self.log("Failure setting mode, quitting.")
            quit()


        self.log("Waiting for mission to finish.")

        while self.last_wp_seq != len(waypoints)-1:
            pass
        # TODO: refactor this mess into a function, and evaluate if this is actually needed.
        for _ in range(1000):
            self.mode_client.call(mavros_msgs.srv.SetMode.Request( \
                base_mode = 0,
                custom_mode = 'AUTO.LOITER'
            ))
            time.sleep(0.2)
            if self.cur_state != None and self.cur_state.mode == 'AUTO.MISSION':
                self.log("Success setting mode")
                break
        else:
            self.log("Failure setting mode, quitting.")
            quit()
    
    def release_payload(self):
        # mocked out for now.
        self.log("WOULD RELEASE PAYLOAD")
    
    def gather_imaging_detections(self):
        detections = []
        self.log("Waiting for imaging detections.")
        for future in self.imaging_futures:
            while not future.done():
                pass
            detections += future.result().detections
        self.imaging_futures = []
        self.log("Successfully retrieved imaging detections:", detections)
        return detections
    
    def wait_for_takeoff(self):
        '''
        Will be executed before the start of each lap. Will wait for a signal
        indicating that the drone has taken off and is ready to fly the next lap.
        '''
        self.log('Waiting for takeoff')

        self.takeoff_client.wait_for_service()

        takeoff_request = mavros_msgs.srv.CommandTOL.Request(altitude=20.0, min_pitch=0.0, yaw=0.0, latitude=0.0, longitude=0.0)
        takeoff_response = self.takeoff_client.call(takeoff_request)

        return takeoff_response.success

    def takeoff(self):
        success = self.wait_for_takeoff()

        if success:
            self.log('Takeoff successful')
        else:
            self.log('Takeoff failed')

        return success

    def wait_for_land(self):
        self.land_client.wait_for_service()

        land_request = mavros_msgs.srv.CommandTOL.Request(altitude=0.0, min_pitch=0.0, yaw=0.0, latitude=0.0, longitude=0.0)
        land_response = self.land_client.call(land_request)

        return land_response.success

    def land(self):
        success = self.wait_for_land()
        
        if success:
            self.log('Landing successful')
        else:
            self.log('Landing failed')

        return success

    def arm(self, b: bool):
        '''
        True for arm
        False for disarm
        '''
        arm_response = self.arm_client.call(mavros_msgs.srv.CommandBool.Request(value = b))
        arm_disarm_string = 'Arming' if b else 'Disarming'
        if arm_response.success:
            self.log(arm_disarm_string + ' successful')
        else:
            self.log(arm_disarm_string + ' failed')
        return arm_response.success

    def reload_payload(self):
        '''
        this will do nothing for now
        '''
        self.log('Nothing will happen for now')
    
    def execute_mission_loop(self):
        while not self.got_global_pos:
            pass

        arm_success = self.arm(True)

        if not arm_success:
            self.log('Mission aborted due to failed arming')
            return
        
        for lap in range(len(self.payloads)):
            self.log('Lap', lap)

            # # Wait for takeoff
            # self.wait_for_takeoff()
            

            takeoff_success = self.takeoff()

            if not takeoff_success:
                self.log('Mission aborted due to failed takeoff')
                return
            
            # Fly waypoint lap
            self.execute_waypoints(self.mission_wps)

            if self.args.exit_early:
                return

            # Fly to drop zone and release current payload
            self.dropzone_planner.conduct_air_drop()

            # Fly back to home position
            self.execute_waypoints([(self.home_global_pos.latitude, self.home_global_pos.longitude)])

            self.reload_payload()

            land_success = self.land()

            if not land_success:
                self.log('Mission aborted due to landing failure.')
                return

        disarm_success = self.arm(False)

        if not disarm_success:
            self.log('Mission aborted due to failed disarming')
            return