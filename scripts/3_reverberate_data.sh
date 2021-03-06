#!/usr/bin/env bash
# Script to reproduce the synthetic data for dcase 2020 task 4 for sound event detection
# Change the parameters in each part of the if depending the case you are in

# We assume you're in the conda envrionment specified

# Be careful The input path should corresponds to OUT_PATH in step 2
DIR_PATH=..
SUBSET=train  # Here the subset is also used to define the subset of RIR to use
INPUT_PATH=${DIR_PATH}/dataset/audio/${SUBSET}/synthetic20

# Reverb default path
RIR=${DIR_PATH}/rir_data


REVERB_PATH=${INPUT_PATH}_reverb
MIX_INFO=${REVERB_PATH}/mix_info.txt
SRC_LIST=${REVERB_PATH}/src_list.txt
RIR_LIST=${REVERB_PATH}/rir_list.txt


NPROC=8 # Be careful, if you do not use the same number of processors, you won't reproduce the baseline data.
SCRIPTS_PATH=../data_generation

######## Under this line you should not have to change anything ###########

# Reverberate data using same RIR as Google baseline
python ${SCRIPTS_PATH}/reverberate_data.py --rir_folder=${RIR} --input_folder=${INPUT_PATH} \
--reverb_out_folder=${REVERB_PATH} --rir_subset=${SUBSET} --mix_info_file=${MIX_INFO}  --src_list_file=${SRC_LIST} \
--rir_list_file=${RIR_LIST} \--nproc=${NPROC}