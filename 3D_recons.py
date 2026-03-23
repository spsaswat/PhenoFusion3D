import torch
np_loc = 0
if torch.cuda.is_available():
    print("GPU is available.")
    import cupy as np
    np_loc = 1
else:
    print("GPU is not available, using numpy instead.")
    import numpy as np

import cv2
import os
import open3d as o3d
import json
import glob
from tqdm import tqdm
from natsort import natsorted
import utils
import copy
import time


"""
This script performs 3D point cloud model reconstruction directly on RGBD images.
"""
def merge_one_cam(record_path, cam_id, step_size):
    try:
        print("Start merging cam {} images".format(cam_id))
        if os.path.exists(os.path.join(record_path, "camera_{}".format(cam_id))):
            record_path = os.path.join(record_path, "camera_{}".format(cam_id))
        save_path = os.path.join(record_path, 'merge')
        if not os.path.exists(save_path):
            os.mkdir(save_path)
        pose_save_path = os.path.join(record_path,'pose')
        if not os.path.exists(pose_save_path):
            os.mkdir(pose_save_path)

        intrinsic_folder = record_path

        with open(os.path.join(intrinsic_folder, 'kdc_intrinsics.txt'), 'r') as infile:
            intrinsics_dict = json.load(infile)
            print('HI')

        K = np.array(intrinsics_dict['K'])
        dist = np.array(intrinsics_dict['dist'])
        print(len(os.listdir(record_path)))
        color_img_files = natsorted(glob.glob(os.path.join(record_path, 'rgb_*.png')))
        print(len(color_img_files))
        depth_img_files = natsorted(glob.glob(os.path.join(record_path, 'depth_*.png')))
        print(len(depth_img_files))
        num_imgs = len(list(color_img_files))
        ds_imgs = int(num_imgs / step_size)
        target = o3d.geometry.PointCloud()
        succeed_list = []
        fail_list = []

        # Get image list
        last_transform = np.eye(4)
        cam_T = np.eye(4)

    #     if cam_id == 0:
    #         bbox = [620, 0, 660, 720]
    #         # bound box for camera position tuned after 05/04
    #         bound_max = [307.70884356862109, 133.03577728238881, 756.01158625186258]
    #         bound_min = [-69.869545476958933, -1512.3899056200662, 379.23399044357382]

    #     else:
    #         bbox = [550, 0, 700, 720]
    #         # bbox for camera position tuned after 11/03
    #         # bbox = [0, 0, 650, 720]
    #         bound_max = [354.69967180042113, 1573.2051127945665, 729.25]
    #         bound_min = [8.5977648813832737, -16.218270431675947, 372.11855887099176]

    #     bbox_crop = o3d.geometry.AxisAlignedBoundingBox(max_bound=bound_max, min_bound=bound_min)

        # TODO: comment off this line
        bbox = None
        for i in range(ds_imgs):
            # Get color and depth, and undistort them
            color_name = color_img_files[i * step_size]
            depth_name = depth_img_files[i * step_size]
            color = cv2.imread(color_name)
            color = cv2.cvtColor(color, cv2.COLOR_BGR2RGB)
            depth = cv2.imread(depth_name, -1)
            source = utils.rgbd2pcd(color, depth, K, bbox=bbox)

            if np_loc == 1:
                source = source.transform(np.asnumpy(cam_T))
            else:
                source = source.transform(cam_T)


            # o3d.visualization.draw_geometries([source])
            source = utils.clean_pcd(source)

            # Check if the point cloud has color data before performing ICP
            # if not source.is_empty():
            #     print(f"Skipping iteration {i} due to missing color data in the point cloud.")
            #     continue

            if i == 0:
                target = source
                succeed_list.append([0, 0, 0])
                reference_pcd = copy.deepcopy(target)
                continue
            # o3d.visualization.draw_geometries([target])



            _, transformation, fitness, inlier_rmse = utils.color_icp(source, target)
            if fitness > 0 or i<3:
                succeed_list.append([0, i * step_size, fitness, inlier_rmse])
                last_transform = np.dot(last_transform, transformation)
                np.savetxt(os.path.join(pose_save_path, '%d_%s_pose.txt' % (i * step_size, cam_id)), last_transform)
                target = source
                reference_pcd += copy.deepcopy(source).transform(last_transform)
                # print("[Frame: %4d/%4d] fitness: %f, rmse: %f" % (i * step_size, num_imgs, fitness, inlier_rmse))
                o3d.io.write_point_cloud(os.path.join(save_path, 'merge_pcd_cam{}.ply'.format(cam_id)), reference_pcd)
            else:
                fail_list.append([0, i * step_size])
                # print("[Frame: %4d/%4d] icp failed! " % (i * step_size, num_imgs))
        # reference_pcd = reference_pcd.crop(bbox_crop)
        o3d.io.write_point_cloud(os.path.join(save_path, 'merge_pcd_cam{}.ply'.format(cam_id)), reference_pcd)
    except KeyboardInterrupt:
        o3d.io.write_point_cloud('./emergency_save.ply', reference_pcd)
        raise  # re-raise the exception to halt execution



if __name__ == "__main__":
    # List of folder names
    # folders = ['test_plant_rs13_1', 'test_plant_rs13_2', 'test_plant_rs13_3', 'test_plant_rs13_4']

    # Directory path
    directory_path = '/home/ubuntu/CSIRO_APPF_Hyperspec/RS_py/data/rs_data_6'
    folders = os.listdir(directory_path)
    # Loop over each folder name
    for folder in folders:
        # Construct the full path for each folder using os.path.join
        full_path = os.path.join(directory_path, folder)
        
        # Call the function
        merge_one_cam(full_path, '', 2)
