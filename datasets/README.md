## Prepare Refer-X Data
### Refer-OVIS & Refer-MOT17 & Refer-MOT20
Detailed steps are shown as follows.

1. Download the official OVIS images from [official website](https://songbai.site/ovis/).
2. Download the official MOT17 images from [official website](https://motchallenge.net/data/MOT17/).
3. Download the official MOT20 images from [official website](https://motchallenge.net/data/MOT20/).
4. Download our created expression and labels_with_ids from [Google Drive](https://drive.google.com/drive/folders/1DwMuSu3kdVvt6bhqAHM4PUnQaaD_jB00?usp=sharing).


The directory structure should be as below, e.g., refer-ovis.
```
.
├── refer-ovis
│   ├── OVIS
│           ├── training
│           ├── labels_with_ids
│   └── expression
```
Note: 
- Since this repository serves as the baseline for the ICCV 2025 Workshop, the original test set will **not** be provided. If you need to test, please split the training set. Create the sequences required for training and testing in the format of refer-x.train and seqmap_x.txt.
- Our expression (.json) contains corresponding object ids, and the corresponding boxes can be found in 'labels_with_ids' using these ids.
- refer-mot17 and refer-mot20 have the same directory structure as refer-ovis.

## Data Format
Each manually annotated expression file is structured like this :
```json
{"label": {"frame_id_start": ["object_ids"],"frame_id": ["object_ids"],"frame_id_end": ["object_ids"]}, "ignore": [], "video_name": "", "sentence": ""}
```

And each expression extended through **GPT-3.5** is structured like this :
```json
{"label": {"frame_id_start": ["object_ids"],"frame_id": ["object_ids"],"frame_id_end": ["object_ids"]}, "ignore": [], "video_name": "", "sentence": "", "raw_sentence": ""}
```
