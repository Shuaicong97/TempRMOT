# ------------------------------------------------------------------------
# Copyright (c) 2021 megvii-model. All Rights Reserved.
# ------------------------------------------------------------------------
# Modified from Deformable DETR (https://github.com/fundamentalvision/Deformable-DETR)
# Copyright (c) 2020 SenseTime. All Rights Reserved.
# ------------------------------------------------------------------------
# Modified from DETR (https://github.com/facebookresearch/detr)
# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
# ------------------------------------------------------------------------

"""
    SORT: A Simple, Online and Realtime Tracker
    Copyright (C) 2016-2020 Alex Bewley alex@bewley.ai
    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.
    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.
    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
from __future__ import print_function

import os
import numpy as np
import random
import argparse
import torchvision.transforms.functional as F
import torch
import cv2
from tqdm import tqdm
from pathlib import Path
from PIL import Image, ImageDraw
from models import build_model
from util.tool import load_model
from main import get_args_parser
from torch.nn.functional import interpolate
from typing import List
from util.evaluation import Evaluator
import motmetrics as mm
import shutil
import json
import matplotlib.pyplot as plt
import copy

from models.structures import Instances
from torch.utils.data import Dataset, DataLoader

import multiprocessing as mp
import threading
import time
import datetime


np.random.seed(2020)

COLORS_10 = [(144, 238, 144), (178, 34, 34), (221, 160, 221), (0, 255, 0), (0, 128, 0), (210, 105, 30), (220, 20, 60),
             (192, 192, 192), (255, 228, 196), (50, 205, 50), (139, 0, 139), (100, 149, 237), (138, 43, 226),
             (238, 130, 238),
             (255, 0, 255), (0, 100, 0), (127, 255, 0), (255, 0, 255), (0, 0, 205), (255, 140, 0), (255, 239, 213),
             (199, 21, 133), (124, 252, 0), (147, 112, 219), (106, 90, 205), (176, 196, 222), (65, 105, 225),
             (173, 255, 47),
             (255, 20, 147), (219, 112, 147), (186, 85, 211), (199, 21, 133), (148, 0, 211), (255, 99, 71),
             (144, 238, 144),
             (255, 255, 0), (230, 230, 250), (0, 0, 255), (128, 128, 0), (189, 183, 107), (255, 255, 224),
             (128, 128, 128),
             (105, 105, 105), (64, 224, 208), (205, 133, 63), (0, 128, 128), (72, 209, 204), (139, 69, 19),
             (255, 245, 238),
             (250, 240, 230), (152, 251, 152), (0, 255, 255), (135, 206, 235), (0, 191, 255), (176, 224, 230),
             (0, 250, 154),
             (245, 255, 250), (240, 230, 140), (245, 222, 179), (0, 139, 139), (143, 188, 143), (255, 0, 0),
             (240, 128, 128),
             (102, 205, 170), (60, 179, 113), (46, 139, 87), (165, 42, 42), (178, 34, 34), (175, 238, 238),
             (255, 248, 220),
             (218, 165, 32), (255, 250, 240), (253, 245, 230), (244, 164, 96), (210, 105, 30)]


def plot_one_box(x, img, color=None, label=None, score=None, line_thickness=None):
    # Plots one bounding box on image img

    # tl = line_thickness or round(
    #     0.002 * max(img.shape[0:2])) + 1  # line thickness
    tl = 10
    color = color or [random.randint(0, 255) for _ in range(3)]
    c1, c2 = (int(x[0]), int(x[1])), (int(x[2]), int(x[3]))
    cv2.rectangle(img.numpy(), c1, c2, color, thickness=tl)
    if label:
        tf = max(tl - 1, 1)  # font thickness
        t_size = cv2.getTextSize(label, 0, fontScale=tl / 3, thickness=tf)[0]
        c2 = c1[0] + t_size[0], c1[1] - t_size[1] - 3
        cv2.rectangle(img.numpy(), c1, c2, color, -1)  # filled
        cv2.putText(img.numpy(),
                    label, (c1[0], c1[1] - 2),
                    0,
                    tl / 3, [225, 255, 255],
                    thickness=tf,
                    lineType=cv2.LINE_AA)
        if score is not None:
            cv2.putText(img.numpy(), score, (c1[0], c1[1] + 30), 0, tl / 3, [225, 255, 255], thickness=tf,
                        lineType=cv2.LINE_AA)
    return img


'''
deep sort 中的画图方法，在原图上进行作画
'''


def draw_bboxes(ori_img, bbox, identities=None, offset=(0, 0), cvt_color=False):
    if cvt_color:
        ori_img = cv2.cvtColor(np.asarray(ori_img), cv2.COLOR_RGB2BGR)
    img = ori_img
    for i, box in enumerate(bbox):
        x1, y1, x2, y2 = [int(i) for i in box[:4]]
        x1 += offset[0]
        x2 += offset[0]
        y1 += offset[1]
        y2 += offset[1]
        if len(box) > 4:
            score = '{:.2f}'.format(box[4])
        else:
            score = None
        # box text and bar
        id = int(identities[i]) if identities is not None else 0
        color = COLORS_10[id % len(COLORS_10)]
        label = '{:d}'.format(id)
        # t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_PLAIN, 2 , 2)[0]
        img = plot_one_box([x1, y1, x2, y2], img, color, label, score=score)
    return img


def draw_points(img: np.ndarray, points: np.ndarray, color=(255, 255, 255)) -> np.ndarray:
    assert len(points.shape) == 2 and points.shape[1] == 2, 'invalid points shape: {}'.format(points.shape)
    for i, (x, y) in enumerate(points):
        if i >= 300:
            color = (0, 255, 0)
        cv2.circle(img, (int(x), int(y)), 2, color=color, thickness=2)
    return img


def tensor_to_numpy(tensor: torch.Tensor) -> np.ndarray:
    return tensor.detach().cpu().numpy()


class Track(object):
    track_cnt = 0

    def __init__(self, box):
        self.box = box
        self.time_since_update = 0
        self.id = Track.track_cnt
        Track.track_cnt += 1
        self.miss = 0

    def miss_one_frame(self):
        self.miss += 1

    def clear_miss(self):
        self.miss = 0

    def update(self, box):
        self.box = box
        self.clear_miss()


class TransRMOT(object):
    def __init__(self, max_age=1, min_hits=3, iou_threshold=0.3):
        """
        Sets key parameters for SORT
        """
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self.trackers = []
        self.frame_count = 0
        self.active_trackers = {}
        self.inactive_trackers = {}
        self.disappeared_tracks = []

    def _remove_track(self, slot_id):
        self.inactive_trackers.pop(slot_id)
        self.disappeared_tracks.append(slot_id)

    def clear_disappeared_track(self):
        self.disappeared_tracks = []

    def update(self, dt_instances: Instances):
        """
        Params:
          dets - a numpy array of detections in the format [[x1,y1,x2,y2,score],[x1,y1,x2,y2,score],...]
        Requires: this method must be called once for each frame even with empty detections (use np.empty((0, 5)) for frames without detections).
        Returns the a similar array, where the last column is the object ID.
        NOTE: The number of objects returned may differ from the number of detections provided.
        """
        self.frame_count += 1
        # get predicted locations from existing trackers.
        dt_idxes = set(dt_instances.obj_idxes.tolist())
        track_idxes = set(self.active_trackers.keys()).union(set(self.inactive_trackers.keys()))
        matched_idxes = dt_idxes.intersection(track_idxes)

        unmatched_tracker = track_idxes - matched_idxes
        for track_id in unmatched_tracker:
            # miss in this frame, move to inactive_trackers.
            if track_id in self.active_trackers:
                self.inactive_trackers[track_id] = self.active_trackers.pop(track_id)
            self.inactive_trackers[track_id].miss_one_frame()
            if self.inactive_trackers[track_id].miss > 10:
                self._remove_track(track_id)

        for i in range(len(dt_instances)):
            idx = dt_instances.obj_idxes[i]
            bbox = np.concatenate([dt_instances.boxes[i], dt_instances.scores[i:i + 1]], axis=-1)
            label = dt_instances.labels[i]
            if label == 0:
                # get a positive track.
                if idx in self.inactive_trackers:
                    # set state of track active.
                    self.active_trackers[idx] = self.inactive_trackers.pop(idx)
                if idx not in self.active_trackers:
                    # create a new track.
                    self.active_trackers[idx] = Track(idx)
                self.active_trackers[idx].update(bbox)
            elif label == 1:
                # get an occluded track.
                if idx in self.active_trackers:
                    # set state of track inactive.
                    self.inactive_trackers[idx] = self.active_trackers.pop(idx)
                if idx not in self.inactive_trackers:
                    # It's strange to obtain a new occluded track.
                    # TODO: think more rational disposal.
                    self.inactive_trackers[idx] = Track(idx)
                self.inactive_trackers[idx].miss_one_frame()
                if self.inactive_trackers[idx].miss > 10:
                    self._remove_track(idx)

        ret = []
        for i in range(len(dt_instances)):
            label = dt_instances.labels[i]
            if label == 0:
                id = dt_instances.obj_idxes[i]
                box_with_score = np.concatenate([dt_instances.boxes[i], dt_instances.scores[i:i + 1]], axis=-1)
                ret.append(
                    np.concatenate((box_with_score, [id + 1])).reshape(1, -1))  # +1 as MOT benchmark requires positive

        if len(ret) > 0:
            return np.concatenate(ret)
        return np.empty((0, 6))


def load_label(label_path: str, img_size: tuple) -> dict:
    labels0 = np.loadtxt(label_path, dtype=np.float32).reshape(-1, 6)
    h, w = img_size
    # Normalized cewh to pixel xyxy format
    labels = labels0.copy()
    labels[:, 2] = w * (labels0[:, 2])
    labels[:, 3] = h * (labels0[:, 3])
    labels[:, 4] = w * (labels0[:, 2] + labels0[:, 4])
    labels[:, 5] = h * (labels0[:, 3] + labels0[:, 5])
    targets = {'boxes': [], 'labels': [], 'area': []}
    num_boxes = len(labels)

    visited_ids = set()
    for label in labels[:num_boxes]:
        obj_id = label[1]
        if obj_id in visited_ids:
            continue
        visited_ids.add(obj_id)
        targets['boxes'].append(label[2:6].tolist())
        targets['area'].append(label[4] * label[5])
        targets['labels'].append(0)
    targets['boxes'] = np.asarray(targets['boxes'])
    targets['area'] = np.asarray(targets['area'])
    targets['labels'] = np.asarray(targets['labels'])
    return targets



class ListImgDataset(Dataset):
    def __init__(self, img_list) -> None:
        super().__init__()
        self.img_list = img_list

        '''
        common settings
        '''
        self.img_height = 360
        self.img_width = 768
        self.mean = [0.485, 0.456, 0.406]
        self.std = [0.229, 0.224, 0.225]

    def load_img_from_file(self, f_path):
        label_path = f_path.replace('training', 'labels_with_ids').replace('.png', '.txt').replace('.jpg', '.txt')
        # print(label_path)
        cur_img = cv2.imread(f_path)
        assert cur_img is not None, f_path
        cur_img = cv2.cvtColor(cur_img, cv2.COLOR_BGR2RGB)
        targets = load_label(label_path, cur_img.shape[:2]) if os.path.exists(label_path) else None
        # img = draw_bboxes(torch.tensor(cur_img), targets['boxes'])
        return cur_img, targets

    def init_img(self, img):
        ori_img = img.copy()
        self.seq_h, self.seq_w = img.shape[:2]
        scale = self.img_height / min(self.seq_h, self.seq_w)
        if max(self.seq_h, self.seq_w) * scale > self.img_width:
            scale = self.img_width / max(self.seq_h, self.seq_w)
        target_h = int(self.seq_h * scale)
        target_w = int(self.seq_w * scale)
        img = cv2.resize(img, (target_w, target_h))
        img = F.normalize(F.to_tensor(img), self.mean, self.std)
        img = img.unsqueeze(0)
        return img, ori_img

    def __len__(self):
        return len(self.img_list)

    def __getitem__(self, index):
        img, targets = self.load_img_from_file(self.img_list[index])
        return self.init_img(img)


class Detector(object):
    def __init__(self, args, checkpoint_id=None, model=None, seq_num=2):

        self.args = args
        self.detr = model
        self.checkpoint_id = checkpoint_id

        self.seq_num = seq_num
        if 'refer-ovis' in args.rmot_path:
            img_list = os.listdir(os.path.join(self.args.rmot_path, 'OVIS/valid', self.seq_num[0]))
            img_list = [os.path.join(self.args.rmot_path, 'OVIS/valid', self.seq_num[0], _)
                        for _ in img_list if ('jpg' in _) or ('png' in _)]
        elif 'refer-mot17' in args.rmot_path:
            img_list = os.listdir(os.path.join(self.args.rmot_path, 'MOT17/valid', self.seq_num[0]))
            img_list = [os.path.join(self.args.rmot_path, 'MOT17/valid', self.seq_num[0], _)
                        for _ in img_list if ('jpg' in _) or ('png' in _)]
        elif 'refer-mot20' in args.rmot_path:
            img_list = os.listdir(os.path.join(self.args.rmot_path, 'MOT20/valid', self.seq_num[0]))
            img_list = [os.path.join(self.args.rmot_path, 'MOT20/valid', self.seq_num[0], _)
                        for _ in img_list if ('jpg' in _) or ('png' in _)]
        else:
            img_list = os.listdir(os.path.join(self.args.rmot_path, 'KITTI/training/image_02', self.seq_num[0]))
            img_list = [os.path.join(self.args.rmot_path, 'KITTI/training/image_02', self.seq_num[0], _)
                        for _ in img_list if ('jpg' in _) or ('png' in _)]

        self.img_list = sorted(img_list)
        self.img_len = len(self.img_list)

        # seq_num[0] = video_name, e.g. MOT20-03, seq_num[1] = query, e.g. the-wheelchair-goes-right.json
        self.json_path = os.path.join(self.args.rmot_path, 'expression/valid', seq_num[0], seq_num[1])
        with open(self.json_path, 'r') as f:
            json_info = json.load(f)
        self.json_info = json_info
        self.sentence = [json_info['sentence']]

        self.tr_tracker = TransRMOT()
        # self.tr_tracker_withouRef = TransRMOT()
        self.save_path = os.path.join(self.args.output_dir,
                                      'results_epoch{}/{}/{}'.format(checkpoint_id, seq_num[0], seq_num[1].split('.')[0]))
        # if os.path.exists(self.save_path):
        #     shutil.rmtree(self.save_path)
        os.makedirs(self.save_path, exist_ok=True)

        self.predict_path = os.path.join(self.args.output_dir, self.args.exp_name)
        os.makedirs(self.predict_path, exist_ok=True)
        if os.path.exists(os.path.join(self.predict_path, f'{self.seq_num}.txt')):
            os.remove(os.path.join(self.predict_path, f'{self.seq_num}.txt'))

    @staticmethod
    def filter_dt_by_score(dt_instances: Instances, prob_threshold: float) -> Instances:
        keep = dt_instances.scores > prob_threshold
        keep &= dt_instances.obj_idxes >= 0
        return dt_instances[keep]

    @staticmethod
    def filter_dt_by_area(dt_instances: Instances, area_threshold: float) -> Instances:
        wh = dt_instances.boxes[:, 2:4] - dt_instances.boxes[:, 0:2]
        areas = wh[:, 0] * wh[:, 1]
        keep = areas > area_threshold
        return dt_instances[keep]

    @staticmethod
    def filter_dt_by_ref_scores(dt_instances: Instances, ref_threshold: float) -> Instances:
        keep = dt_instances.refers > ref_threshold
        return dt_instances[keep]

    @staticmethod
    def write_results(txt_path, frame_id, bbox_xyxy, identities):
        save_format = '{frame},{id},{x1},{y1},{w},{h},1,1,1\n'
        with open(txt_path, 'a') as f:
            for xyxy, track_id in zip(bbox_xyxy, identities):
                if track_id < 0 or track_id is None:
                    continue
                x1, y1, x2, y2 = xyxy
                w, h = x2 - x1, y2 - y1
                line = save_format.format(frame=int(frame_id), id=int(track_id), x1=x1, y1=y1, w=w, h=h)
                f.write(line)

    # write ground-truth for each expression in a text. The text includes gt of all frames
    @staticmethod
    def write_gt(txt_path, json_file, gt_txt_file, im_height, im_width):
        save_format = '{frame},{id},{x1},{y1},{w},{h},1, 1, 1\n'

        with open(json_file) as f:
            json_info = json.load(f)

        with open(txt_path, 'w') as f:
            for k in json_info['label'].keys():
                frame_id = int(k)
                if not os.path.isfile(os.path.join(gt_txt_file, '{:06d}.txt'.format(frame_id))):
                    continue
                frame_gt = np.loadtxt(
                    os.path.join(gt_txt_file, '{:06d}.txt'.format(frame_id))).reshape(-1, 6)
                for frame_gt_line in frame_gt:
                    aa = json_info['label'][k]  # all gt from frame
                    aa = [int(a) for a in aa]
                    if int(frame_gt_line[1]) in aa:  # choose referent gt from all gt
                        track_id = int(frame_gt_line[1])
                        x1, y1, w, h = frame_gt_line[2:6] # KITTI -> [x1, y1, w, h]
                        line = save_format.format(frame=frame_id, id=track_id, x1=x1 * im_width, y1=y1 * im_height,
                                                  w=w * im_width, h=h * im_height)
                        f.write(line)

        print('save gt to {}'.format(txt_path))

    @staticmethod
    def visualize_img_with_bbox(img_path, img, dt_instances: Instances, ref_pts=None, gt_boxes=None):
        if dt_instances.has('scores'):
            img_show = draw_bboxes(img,
                                   np.concatenate([dt_instances.boxes, dt_instances.scores.reshape(-1, 1)], axis=-1),
                                   dt_instances.obj_idxes)
        else:
            img_show = draw_bboxes(img, dt_instances.boxes, dt_instances.obj_idxes)
        if ref_pts is not None:
            img_show = draw_points(img_show, ref_pts)
        # if gt_boxes is not None:
        #     img_show = draw_bboxes(img_show, gt_boxes, identities=np.ones((len(gt_boxes),)) * -1)
        cv2.imwrite(img_path, cv2.cvtColor(img_show.numpy(), cv2.COLOR_RGB2BGR))

    def detect(self, prob_threshold=0.4, area_threshold=100):
        last_dt_embedding = None
        total_dts = 0
        total_occlusion_dts = 0
        print('Results are saved into {}'.format(self.save_path))

        track_instances = None
        loader = DataLoader(ListImgDataset(self.img_list), 1, num_workers=2)
        for i, (cur_img, ori_img) in enumerate(tqdm(loader)):
            cur_img, ori_img = cur_img[0], ori_img[0]

            # track_instances = None
            if track_instances is not None:
                track_instances.remove('boxes')
                track_instances.remove('labels')
            seq_h, seq_w, _ = ori_img.shape

            res = self.detr.inference_single_image(cur_img.cuda().float(), self.sentence, (seq_h, seq_w),
                                                   track_instances)
            track_instances = res['track_instances']

            all_ref_pts = tensor_to_numpy(res['ref_pts'][0, :, :2])
            dt_instances = track_instances.to(torch.device('cpu'))

            # filter det instances by score. (visual detections)
            dt_instances = self.filter_dt_by_score(dt_instances, prob_threshold)
            dt_instances = self.filter_dt_by_area(dt_instances, area_threshold)

            # filter det instances by refer scores (query matching)
            dt_instances = self.filter_dt_by_ref_scores(dt_instances, 0.3)

            num_occlusion = (dt_instances.labels == 1).sum()
            dt_instances.scores[dt_instances.labels == 1] *= -1
            total_dts += len(dt_instances)
            total_occlusion_dts += num_occlusion

            if self.args.visualization and len(dt_instances) > 0:
                # for visual
                cur_vis_img_path = os.path.join(self.save_path, 'frame_{}.jpg'.format(i+1))
                gt_boxes = None
                self.visualize_img_with_bbox(cur_vis_img_path, ori_img, dt_instances, gt_boxes=gt_boxes)

            tracker_outputs = self.tr_tracker.update(dt_instances)

            self.write_results(txt_path=os.path.join(self.save_path, 'predict.txt'),
                               frame_id=(i + 1),
                               bbox_xyxy=tracker_outputs[:, :4],
                               identities=tracker_outputs[:, 5])
        gt_path = os.path.join(self.save_path, 'gt.txt')
        if 'refer-ovis' in self.args.rmot_path:
            self.write_gt(gt_path, self.json_path,
                          os.path.join(self.args.rmot_path, 'OVIS/labels_with_ids/valid', self.seq_num[0]), seq_h, seq_w)
        if 'refer-mot17' in self.args.rmot_path:
            self.write_gt(gt_path, self.json_path,
                          os.path.join(self.args.rmot_path, 'MOT17/labels_with_ids/valid', self.seq_num[0]), seq_h, seq_w)
        if 'refer-mot20' in self.args.rmot_path:
            self.write_gt(gt_path, self.json_path,
                          os.path.join(self.args.rmot_path, 'MOT20/labels_with_ids/valid', self.seq_num[0]), seq_h, seq_w)

        print("totally {} dts {} occlusion dts".format(total_dts, total_occlusion_dts))

def sub_processor(pid,seq_nums,args):
    # load model and weights
    torch.cuda.set_device(pid)
    detr, _, _ = build_model(args)
    checkpoint = torch.load(args.resume, map_location='cpu')
    checkpoint_id = int(args.resume.split('/')[-1].split('.')[0].split('t')[-1])
    detr = load_model(detr, args.resume)
    detr.eval()
    detr = detr.cuda()

    # device = args.device
    # detr.to(device)
    for seq_num in seq_nums:
        print('Evaluating seq {}'.format(seq_num))
        det = Detector(args, checkpoint_id, model=detr, seq_num=seq_num)
        det.detect()

if __name__ == '__main__':
    torch.multiprocessing.set_start_method('spawn')
    parser = argparse.ArgumentParser('DETR training and evaluation script', parents=[get_args_parser()])
    args0 = parser.parse_args()
    if args0.output_dir:
        Path(args0.output_dir).mkdir(parents=True, exist_ok=True)

    expressions_root = os.path.join(args0.rmot_path, 'expression/valid')
    if "refer-kitti-v2" in args0.rmot_path:
        video_ids = ['0005', '0011', '0013','0019']
    elif "refer-ovis" in args0.rmot_path:
        # 137 valid videos
        video_ids = ['c34989e3', 'ac8ecb27', 'af48b2f9', '15e09c8c', '505ed57c', '7223bf62', 'c9a2645e', '2112a80d',
                     'fb57abac', 'f10e23dd', '48cd08af', '1a4b95d3', '63263f3f', '6a47103e', '2a02f752', '9069547d',
                     '2d802cb8', '68d9fb6a', '95a50b7d', '2ca20519', 'e7ef3b9d', 'ed82ce50', '0299d8d6', 'd33e1c97',
                     '4d63d7df', 'ca440c64', 'e568ca41', '2b84174e', '95718597', '4d6a99ec', 'c705c014', '3c4f150c',
                     '97f5bbc8', '7a8cfc91', '90d7f538', 'a42fcfa9', 'ff64095e', 'aa925437', 'f9bee2e2', '1aa4e7f6',
                     '30446667', '2b6e117d', 'b8e00b22', '1b664206', '429d96d4', '2ab06287', '19615388', '2c22cd4e',
                     '35dff164', '012b09a0', 'd4f4cf55', '6976cf19', 'd3ba30b3', 'd50fa72e', '1f17cd7c', 'd501f685',
                     '2a19d8a2', 'c89239d8', 'c4fd77f2', '75a8cadb', '3c5e3be8', 'a5249886', '8b935b9f', 'f4b271d4',
                     'ef81cd52', 'a10de0fc', '9ed568e9', 'b643add8', 'd084134f', 'ec6fd219', '6073aa21', 'ed5ec3c5',
                     '71d35513', '3d8b1ee0', '4027a35b', '06eb2803', '2b827e3a', '1ef6cb7b', 'a16e9661', '69398c01',
                     '257cca89', 'e78253f1', 'c587e43b', 'd41a62d4', '768c5810', 'a74b52eb', 'caf53839', 'c4ecad66',
                     '2cc7839e', 'c7543b31', 'b7b9f632', 'cfff47c3', 'ba5644c3', '2bd72d60', 'aaa8bd16', 'd26036cd',
                     '6a6547d7', 'bd34e772', '86b8e4ec', '39f0d139', '435d99e0', 'e0a22a9b', '5251dbb9', 'b87840e1',
                     '9323c19c', '3054dbaf', 'c7b07fea', 'a87bbd47', 'e3d901dd', 'b692e3cb', '2d0f3000', 'b97c4e2b',
                     '567bfc5a', 'd0a07d68', 'f6cdaca7', '9b318a9c', '1806a28d', '5834b092', '3d04522a', '15e281a9',
                     '1220b722', '454c7bb5', '44a4d836', '957c33a7', '0d0030a7', 'aa8df541', 'fb4a7958', 'c29ce49d',
                     '6312935f', '817263d6', 'c9dfbd0c', '1123fd76', 'cfe04aff', '6c88a53b', 'f326bfb7', '7e52df6a',
                     'ebd1dbad']
    elif "refer-mot17" in args0.rmot_path:
        video_ids = ['MOT17-01', 'MOT17-03', 'MOT17-06', 'MOT17-07', 'MOT17-08', 'MOT17-12', 'MOT17-14']
    elif "refer-mot20" in args0.rmot_path:
        video_ids = ['MOT20-03', 'MOT20-05']
    else:
        video_ids = ['0005', '0011', '0013']

    seq_nums = [] 
    for video_id in video_ids:  
        expression_jsons = sorted(os.listdir(os.path.join(expressions_root, video_id)))
        for expression_json in expression_jsons:
            seq_nums.append([video_id, expression_json])

    thread_num = 4
    processes = []

    expression_num = len(seq_nums)
    per_thread_seq_num = expression_num // thread_num

    print("Start inference")
    start_time = time.time()

    for i in range(thread_num):
        if i == thread_num -1:
            sub_seq_list = seq_nums[i*per_thread_seq_num:]
        else:
            sub_seq_list = seq_nums[i*per_thread_seq_num:(i+1)*per_thread_seq_num]
        p = mp.Process(target=sub_processor,args=(i,sub_seq_list,args0))
        p.start()
        processes.append(p)
    
    for p in processes:
        p.join()

    print("Over")
    total_time = time.time() - start_time
    total_time_str = str(datetime.timedelta(seconds=int(total_time)))
    print('Inference time {}'.format(total_time_str))
