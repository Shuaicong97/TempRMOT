PRETRAIN=/nfs/data3/shuaicong/RMOT/r50_deformable_detr_plus_iterative_bbox_refinement-checkpoint.pth
EXP_DIR=ovis
OUT='/nfs/data3/shuaicong/RMOT/outputs'
TRAIN_LOG_FILE="$OUT/${EXP_DIR}/train_log.txt"
PID_FILE="$OUT/${EXP_DIR}/train_pid.txt"

mkdir -p "$OUT/${EXP_DIR}"

> $TRAIN_LOG_FILE  # clear the log file first
echo $$ > $PID_FILE

python3  -m torch.distributed.launch --nproc_per_node=8 --master_port 29505 \
   --use_env main.py \
   --meta_arch temp_rmot \
   --use_checkpoint \
   --dataset_file e2e_rmot \
   --epoch 60 \
   --with_box_refine \
   --lr_drop 40 \
   --lr 1e-4 \
   --lr_backbone 1e-5 \
   --pretrained ${PRETRAIN}\
   --output_dir $OUT/${EXP_DIR} \
   --save_dir $OUT/${EXP_DIR} \
   --batch_size 1 \
   --sample_mode random_interval \
   --sample_interval 1 \
   --sampler_steps 60 80 90 \
   --sampler_lengths 5 5 5 5 \
   --update_query_pos \
   --merger_dropout 0 \
   --dropout 0 \
   --random_drop 0.1 \
   --fp_ratio 0.3 \
   --query_interaction_layer QIM \
   --data_txt_path_train ./datasets/data_path/refer-ovis.train \
   --hist_len 5 \
   --refer_loss_coef 2 \
   --rmot_path /nfs/data3/shuaicong/refer-ovis | tee -a ${TRAIN_LOG_FILE}


