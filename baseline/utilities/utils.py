from __future__ import print_function

import glob
import warnings

import numpy as np
import pandas as pd
import soundfile
import os
import os.path as osp
import librosa
import torch
from desed.utils import create_folder
from torch import nn
from dcase_util.data import DecisionEncoder

import config as cfg


class ManyHotEncoder:
    """"
        Adapted after DecisionEncoder.find_contiguous_regions method in
        https://github.com/DCASE-REPO/dcase_util/blob/master/dcase_util/data/decisions.py

        Encode labels into numpy arrays where 1 correspond to presence of the class and 0 absence.
        Multiple 1 can appear on the same line, it is for multi label problem.
    Args:
        labels: list, the classes which will be encoded
        n_frames: int, (Default value = None) only useful for strong labels. The number of frames of a segment.
    Attributes:
        labels: list, the classes which will be encoded
        n_frames: int, only useful for strong labels. The number of frames of a segment.
    """
    def __init__(self, labels, n_frames=None):
        if type(labels) in [np.ndarray, np.array]:
            labels = labels.tolist()
        self.labels = labels
        self.n_frames = n_frames

    def encode_weak(self, labels):
        """ Encode a list of weak labels into a numpy array

        Args:
            labels: list, list of labels to encode (to a vector of 0 and 1)

        Returns:
            numpy.array
            A vector containing 1 for each label, and 0 everywhere else
        """
        # useful for tensor empty labels
        if type(labels) is str:
            if labels == "empty":
                y = np.zeros(len(self.labels)) - 1
                return y
        if type(labels) is pd.DataFrame:
            if labels.empty:
                labels = []
            elif "event_label" in labels.columns:
                labels = labels["event_label"]
        y = np.zeros(len(self.labels))
        for label in labels:
            if not pd.isna(label):
                i = self.labels.index(label)
                y[i] = 1
        return y

    def encode_strong_df(self, label_df):
        """Encode a list (or pandas Dataframe or Serie) of strong labels, they correspond to a given filename

        Args:
            label_df: pandas DataFrame or Series, contains filename, onset (in frames) and offset (in frames)
                If only filename (no onset offset) is specified, it will return the event on all the frames
                onset and offset should be in frames
        Returns:
            numpy.array
            Encoded labels, 1 where the label is present, 0 otherwise
        """

        assert self.n_frames is not None, "n_frames need to be specified when using strong encoder"
        if type(label_df) is str:
            if label_df == 'empty':
                y = np.zeros((self.n_frames, len(self.labels))) - 1
                return y
        y = np.zeros((self.n_frames, len(self.labels)))
        if type(label_df) is pd.DataFrame:
            if {"onset", "offset", "event_label"}.issubset(label_df.columns):
                for _, row in label_df.iterrows():
                    if not pd.isna(row["event_label"]):
                        i = self.labels.index(row["event_label"])
                        onset = int(row["onset"])
                        offset = int(row["offset"])
                        y[onset:offset, i] = 1  # means offset not included (hypothesis of overlapping frames, so ok)

        elif type(label_df) in [pd.Series, list, np.ndarray]:  # list of list or list of strings
            if type(label_df) is pd.Series:
                if {"onset", "offset", "event_label"}.issubset(label_df.index):  # means only one value
                    if not pd.isna(label_df["event_label"]):
                        i = self.labels.index(label_df["event_label"])
                        onset = int(label_df["onset"])
                        offset = int(label_df["offset"])
                        y[onset:offset, i] = 1
                    return y

            for event_label in label_df:
                # List of string, so weak labels to be encoded in strong
                if type(event_label) is str:
                    if event_label is not "":
                        i = self.labels.index(event_label)
                        y[:, i] = 1

                # List of list, with [label, onset, offset]
                elif len(event_label) == 3:
                    if event_label[0] is not "":
                        i = self.labels.index(event_label[0])
                        onset = int(event_label[1])
                        offset = int(event_label[2])
                        y[onset:offset, i] = 1

                else:
                    raise NotImplementedError("cannot encode strong, type mismatch: {}".format(type(event_label)))

        else:
            raise NotImplementedError("To encode_strong, type is pandas.Dataframe with onset, offset and event_label"
                                      "columns, or it is a list or pandas Series of event labels, "
                                      "type given: {}".format(type(label_df)))
        return y

    def decode_weak(self, labels):
        """ Decode the encoded weak labels
        Args:
            labels: numpy.array, the encoded labels to be decoded

        Returns:
            list
            Decoded labels, list of string

        """
        result_labels = []
        for i, value in enumerate(labels):
            if value == 1:
                result_labels.append(self.labels[i])
        return result_labels

    def decode_strong(self, labels):
        """ Decode the encoded strong labels
        Args:
            labels: numpy.array, the encoded labels to be decoded
        Returns:
            list
            Decoded labels, list of list: [[label, onset offset], ...]

        """
        result_labels = []
        for i, label_column in enumerate(labels.T):
            change_indices = DecisionEncoder().find_contiguous_regions(label_column)

            # append [label, onset, offset] in the result list
            for row in change_indices:
                result_labels.append([self.labels[i], row[0], row[1]])
        return result_labels

    def state_dict(self):
        return {"labels": self.labels,
                "n_frames": self.n_frames}

    @classmethod
    def load_state_dict(cls, state_dict):
        labels = state_dict["labels"]
        n_frames = state_dict["n_frames"]
        return cls(labels, n_frames)


def read_audio(path, target_fs=None):
    """ Read a wav file
    Args:
        path: str, path of the audio file
        target_fs: int, (Default value = None) sampling rate of the returned audio file, if not specified, the sampling
            rate of the audio file is taken

    Returns:
        tuple
        (numpy.array, sampling rate), array containing the audio at the sampling rate given

    """
    (audio, fs) = soundfile.read(path)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    if target_fs is not None and fs != target_fs:
        audio = librosa.resample(audio, orig_sr=fs, target_sr=target_fs)
        fs = target_fs
    return audio, fs


def weights_init(m):
    """ Initialize the weights of some layers of neural networks, here Conv2D, BatchNorm, GRU, Linear
        Based on the work of Xavier Glorot
    Args:
        m: the model to initialize
    """
    classname = m.__class__.__name__
    if classname.find('Conv2d') != -1:
        nn.init.xavier_uniform_(m.weight, gain=np.sqrt(2))
        m.bias.data.fill_(0)
    elif classname.find('BatchNorm') != -1:
        m.weight.data.normal_(1.0, 0.02)
        m.bias.data.fill_(0)
    elif classname.find('GRU') != -1:
        for weight in m.parameters():
            if len(weight.size()) > 1:
                nn.init.orthogonal_(weight.data)
    elif classname.find('Linear') != -1:
        m.weight.data.normal_(0, 0.01)
        m.bias.data.zero_()


def to_cuda_if_available(*args):
    """ Transfer object (Module, Tensor) to GPU if GPU available
    Args:
        args: torch object to put on cuda if available (needs to have object.cuda() defined)

    Returns:
        Objects on GPU if GPUs available
    """
    res = list(args)
    if torch.cuda.is_available():
        for i, torch_obj in enumerate(args):
            res[i] = torch_obj.cuda()
    if len(res) == 1:
        return res[0]
    return res


class SaveBest:
    """ Callback to get the best value and epoch
    Args:
        val_comp: str, (Default value = "inf") "inf" or "sup", inf when we store the lowest model, sup when we
            store the highest model
    Attributes:
        val_comp: str, "inf" or "sup", inf when we store the lowest model, sup when we
            store the highest model
        best_val: float, the best values of the model based on the criterion chosen
        best_epoch: int, the epoch when the model was the best
        current_epoch: int, the current epoch of the model
    """
    def __init__(self, val_comp="inf"):
        self.comp = val_comp
        if val_comp == "inf":
            self.best_val = np.inf
        elif val_comp == "sup":
            self.best_val = 0
        else:
            raise NotImplementedError("value comparison is only 'inf' or 'sup'")
        self.best_epoch = 0
        self.current_epoch = 0

    def apply(self, value):
        """ Apply the callback
        Args:
            value: float, the value of the metric followed
        """
        decision = False
        if self.current_epoch == 0:
            decision = True
        if (self.comp == "inf" and value < self.best_val) or (self.comp == "sup" and value > self.best_val):
            self.best_epoch = self.current_epoch
            self.best_val = value
            decision = True
        self.current_epoch += 1
        return decision


class EarlyStopping:
    """ Callback to stop training if the metric have not improved during multiple epochs.
    Args:
        patience: int, number of epochs with no improvement before stopping the model
        val_comp: str, (Default value = "inf") "inf" or "sup", inf when we store the lowest model, sup when we
            store the highest model
    Attributes:
        patience: int, number of epochs with no improvement before stopping the model
        val_comp: str, "inf" or "sup", inf when we store the lowest model, sup when we
            store the highest model
        best_val: float, the best values of the model based on the criterion chosen
        best_epoch: int, the epoch when the model was the best
        current_epoch: int, the current epoch of the model
    """
    def __init__(self, patience, val_comp="inf", init_patience=0):
        self.patience = patience
        self.first_early_wait = init_patience
        self.val_comp = val_comp
        if val_comp == "inf":
            self.best_val = np.inf
        elif val_comp == "sup":
            self.best_val = 0
        else:
            raise NotImplementedError("value comparison is only 'inf' or 'sup'")
        self.current_epoch = 0
        self.best_epoch = 0

    def apply(self, value):
        """ Apply the callback

        Args:
            value: the value of the metric followed
        """
        current = False
        if self.val_comp == "inf":
            if value < self.best_val:
                current = True
        if self.val_comp == "sup":
            if value > self.best_val:
                current = True
        if current:
            self.best_val = value
            self.best_epoch = self.current_epoch
        elif self.current_epoch - self.best_epoch > self.patience and self.current_epoch > self.first_early_wait:
            self.current_epoch = 0
            return True
        self.current_epoch += 1
        return False


class AverageMeterSet:
    def __init__(self):
        self.meters = {}

    def __getitem__(self, key):
        return self.meters[key]

    def update(self, name, value, n=1):
        if name not in self.meters:
            self.meters[name] = AverageMeter()
        self.meters[name].update(value, n)

    def reset(self):
        for meter in self.meters.values():
            meter.reset()

    def values(self, postfix=''):
        return {name + postfix: meter.val for name, meter in self.meters.items()}

    def averages(self, postfix='/avg'):
        return {name + postfix: meter.avg for name, meter in self.meters.items()}

    def sums(self, postfix='/sum'):
        return {name + postfix: meter.sum for name, meter in self.meters.items()}

    def counts(self, postfix='/count'):
        return {name + postfix: meter.count for name, meter in self.meters.items()}

    def __str__(self):
        string = ""
        for name, meter in self.meters.items():
            fmat = ".4f"
            if meter.val < 0.01:
                fmat = ".2E"
            string += "{} {:{format}} \t".format(name, meter.val, format=fmat)
        return string


class AverageMeter:
    """Computes and stores the average and current value"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count

    def __format__(self, format):
        return "{self.avg:{format}}".format(self=self, format=format)


def generate_tsv_wav_durations(audio_dir, out_tsv):
    """ Generate a dataframe with filename and duration of the file
    Args:
        audio_dir: str, the path of the folder where audio files are (used by glob.glob)
        out_tsv: str, the path of the output tsv file

    Returns:
        pd.DataFrame, the dataframe containing filenames and durations
    """
    meta_list = []
    for file in glob.glob(os.path.join(audio_dir, "*.wav")):
        d = soundfile.info(file).duration
        meta_list.append([os.path.basename(file), d])
    meta_df = pd.DataFrame(meta_list, columns=["filename", "duration"])
    if out_tsv is not None:
        meta_df.to_csv(out_tsv, sep="\t", index=False, float_format="%.1f")
    return meta_df


def generate_tsv_from_isolated_events(wav_folder, out_tsv=None):
    """ Generate list of separated wav files in a folder and export them in a tsv file
    Separated audio files considered are all wav files in 'subdirectories' of the 'wav_folder'
    Args:
        wav_folder: str, path of the folder containing subdirectories (one for each mixture separated)
        out_tsv: str, path of the csv in which to save the list of files
    Returns:
        pd.DataFrame, having only one column with the filename considered
    """
    if out_tsv is not None and os.path.exists(out_tsv):
        source_sep_df = pd.read_csv(out_tsv, sep="\t")
    else:
        source_sep_df = pd.DataFrame()
        list_dirs = [d for d in os.listdir(wav_folder) if osp.isdir(osp.join(wav_folder, d))]
        for dirname in list_dirs:
            list_isolated_files = []
            for directory, subdir, fnames in os.walk(osp.join(wav_folder, dirname)):
                for fname in fnames:
                    if osp.splitext(fname)[1] in [".wav"]:
                        # Get the level folders and keep it in the tsv
                        subfolder = directory.split(dirname + os.sep)[1:]
                        if len(subfolder) > 0:
                            subdirs = osp.join(*subfolder)
                        else:
                            subdirs = ""
                        # Append the subfolders and name in the list of files
                        list_isolated_files.append(osp.join(dirname, subdirs, fname))
                    else:
                        warnings.warn(f"Not only wav audio files in the separated source folder,"
                                      f"{fname} not added to the .tsv file")
            source_sep_df = source_sep_df.append(pd.DataFrame(list_isolated_files, columns=["filename"]))
        if out_tsv is not None:
            create_folder(os.path.dirname(out_tsv))
            source_sep_df.to_csv(out_tsv, sep="\t", index=False, float_format="%.3f")
    return source_sep_df


def meta_path_to_audio_dir(tsv_path):
    return os.path.splitext(tsv_path.replace("metadata", "audio"))[0]


def audio_dir_to_meta_path(audio_dir):
    return audio_dir.replace("audio", "metadata") + ".tsv"


def get_durations_df(gtruth_path, audio_dir=None):
    if audio_dir is None:
        audio_dir = meta_path_to_audio_dir(cfg.synthetic)
    path, ext = os.path.splitext(gtruth_path)
    path_durations_synth = path + "_durations" + ext
    if not os.path.exists(path_durations_synth):
        durations_df = generate_tsv_wav_durations(audio_dir, path_durations_synth)
    else:
        durations_df = pd.read_csv(path_durations_synth, sep="\t")
    return durations_df