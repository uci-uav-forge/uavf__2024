from uavf_2024.gnc.payload import Payload
from geographiclib.geodesic import Geodesic
import numpy as np
from shapely.geometry import Point, Polygon

def is_point_within_fence(point, fence):
    # Convert the list of tuples representing the border to a Shapely Polygon
    fence_polygon = Polygon(fence)
    point = Point(point)
    return fence_polygon.contains(point)

def validate_gps_data(data, geofence):
    for point_tuple in data:
        if not is_point_within_fence(point_tuple, geofence):
            return False
    return True

def read_geofence(fname):
    # Creates a list of tuples of (lat, lon) of the geofence
    with open(fname) as f:
        return [tuple(map(float, line.split(','))) for line in f]

def read_gps(fname, geofence):
    with open(fname) as f:
        data = [tuple(map(float, line.split(','))) for line in f]
    if validate_gps_data(data, geofence): # Passes coords to validate that they're within the geofence
        return data
    else:
        raise ValueError("Invalid GPS data format or outside geofence boundaries.")

def read_payload_list(fname):
    with open(fname) as f:
        return [Payload(line.split(',')) for line in f]

def convert_delta_gps_to_local_m(gp1, gp2):
    geod = Geodesic.WGS84
    g0 = geod.Inverse(*gp1, gp2[0], gp1[1])
    g1 = geod.Inverse(gp2[0], gp1[1], *gp2)

    return np.array([g1['s12'], -g0['s12']])

def convert_local_m_to_delta_gps(gp0, dm):
    geod = Geodesic.WGS84

    azi = np.degrees(np.arctan2(dm[0], dm[1]))
    len = np.linalg.norm(dm)

    gr = geod.Direct(*gp0, azi, len)
    print(azi, len)

    return np.array([gr['lat2'], gr['lon2']])

def calculate_turn_angles_deg(path_coordinates):
    norm_vectors = []

    for i in range(len(path_coordinates) - 1):
        tail_x, tail_y = path_coordinates[i][0], path_coordinates[i][1]
        head_x, head_y = path_coordinates[i + 1][0], path_coordinates[i + 1][1]
        
        result_vector = np.array([head_x - tail_x, head_y - tail_y])
        norm_vectors.append(result_vector / np.linalg.norm(result_vector))

    turn_angles = []
    for i in range(len(norm_vectors) - 1):
        turn_angles.append(np.degrees(np.arccos(np.dot(norm_vectors[i], norm_vectors[i + 1]))))
    
    return turn_angles