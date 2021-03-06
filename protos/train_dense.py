import os
import sys
import glob
import json
import random
import pickle
import gc
import numpy as np
import scipy.sparse as sp
import pandas as pd
import tensorflow as tf
from keras.callbacks import Callback, EarlyStopping, ReduceLROnPlateau, ModelCheckpoint, TensorBoard
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from dense import get_dense, LIST_DATA_COL, LIST_CONV_COL, LIST_FLOAT_COL, LIST_CAT_COL
import dask.dataframe as ddf
import dask.multiprocessing
from tqdm import tqdm
from multiprocessing.pool import Pool
batch_size = 50000

np.random.seed(0)

from logging import getLogger

logger = getLogger(None)

DTYPE = None
_DTYPE = {'click_id': np.float32,
          'ip': np.float32,
          'app': np.float32,
          'device': np.float32,
          'os': np.float32,
          'channel': np.float32,
          'click_time': str,
          'attributed_time': str,
          'is_attributed': np.float32,
          'timediff': np.float32,
          'year': np.uint16,
          'month': np.uint8,
          'day': np.uint8,
          'dayofweek': np.uint16,
          'hour': np.uint16,
          'avg_ip': np.uint16,
          'sum_attr': np.uint16,
          'last_attr': np.float32,
          'avg_app': np.float32,
          'avg_device': np.float32,
          'avg_os': np.float32,
          'avg_channel': np.float32,
          'avg_day': np.float32,
          'avg_hour': np.float32
          }


try:
    param_file = sys.argv[1]
    with open(param_file) as f:
        model_params = json.loads(f.read())
except IndexError:
    param_file = None
    model_params = {'first_dences': [64, 32, 32, 8],  # [128, 32, 32],
                    'learning_rate': 0.001,
                    }


import gzip


def calc_batch_num(paths):
    cnt = 0
    for path in tqdm(paths):
        tmp = sum(1 for line in gzip.open(path)) - 1
        cnt += len(range(0, tmp, batch_size))
    return cnt


def data_generator(paths, repeat=True):
    while True:
        for path in paths:
            logger.debug(path)
            sv = 'cache2/train/' + path.split('/')[-1].split('.')[0] + '.gz'
            if os.path.exists(sv):
                df = pd.read_pickle(sv)
            else:
                df = pd.read_csv(path, dtype=DTYPE)
                df.to_pickle(sv, protocol=-1)
            df = df.take(np.random.permutation(len(df))).reset_index(drop=True).fillna(-1)
            for start in range(0, df.shape[0], batch_size):
                end = min(start + batch_size, df.shape[0])
                data = df.iloc[start:end]

                targets = np.array(data['is_attributed'].values)
                float_data = data[LIST_FLOAT_COL].values
                cat_data = [data[col].values for col in LIST_CAT_COL]
                x_batch = [float_data] + cat_data
                y_batch = targets

                yield x_batch, y_batch
            del df
            gc.collect()
        if not repeat:
            break


from sklearn.metrics import roc_auc_score


class LoggingCallback(Callback):
    """Callback that logs message at end of epoch.
    """

    def __init__(self, valid_path):
        self.valid_path = valid_path
        self.valid_data = list(data_generator(self.valid_path, repeat=False))

    def on_epoch_end(self, epoch, logs={}):
        labels = []
        preds = []
        for x_batch, y_batch in self.valid_data:

            labels += y_batch.tolist()
            pred = self.model.predict_on_batch(x_batch)[:, 0]
            preds += pred.tolist()  # x_batch[:, 7].tolist()
        auc = roc_auc_score(labels, preds)
        msg = "Epoch: %i, %s" % (epoch, ", ".join("%s: %f" % (k, logs[k]) for k in sorted(logs))) + f', auc: {auc}'
        logger.info(msg)


def main():
    from logging import StreamHandler, DEBUG, Formatter, FileHandler
    DIR = './'

    log_fmt = Formatter('%(asctime)s %(name)s %(lineno)d [%(levelname)s][%(funcName)s] %(message)s ')

    handler = StreamHandler()
    handler.setLevel('INFO')
    handler.setFormatter(log_fmt)
    logger.setLevel('INFO')
    logger.addHandler(handler)

    handler = FileHandler(DIR + 'train.py.log', 'a')
    handler.setLevel(DEBUG)
    handler.setFormatter(log_fmt)
    logger.setLevel(DEBUG)
    logger.addHandler(handler)

    logger.info(f'file: {param_file}, params: {model_params}')
    paths = sorted(glob.glob('../data/dmt_train_raw/*.csv.gz'))
    train_path, valid_path = train_test_split(paths, test_size=0.2, random_state=42)

    #train_path = paths[:-2]
    #valid_path = paths[-2:]
    # steps_per_epoch: 1784, validation_steps: 74
    steps_per_epoch = 148  # calc_batch_num(train_path)
    validation_steps = 148  # calc_batch_num(valid_path)
    metric = 'val_loss'
    mode = 'min'
    callbacks = [EarlyStopping(monitor=metric,
                               patience=3,
                               verbose=1,
                               min_delta=1e-8,
                               mode=mode),
                 ReduceLROnPlateau(monitor=metric,
                                   factor=0.1,
                                   patience=2,
                                   verbose=1,
                                   epsilon=1e-8,
                                   mode=mode),
                 ModelCheckpoint(monitor=metric,
                                 filepath='weights/best_weights.hdf5',
                                 save_best_only=True,
                                 save_weights_only=True,
                                 mode=mode),
                 TensorBoard(log_dir='logs'),
                 LoggingCallback(valid_path)
                 ]

    logger.info(f'steps_per_epoch: {steps_per_epoch}, validation_steps: {validation_steps}')

    model = get_dense(**model_params)
    # model.load_weights(filepath='weights/best_weights.hdf5')

    epochs = 10000
    model.fit_generator(generator=data_generator(train_path),
                        steps_per_epoch=steps_per_epoch,
                        epochs=epochs,
                        verbose=2,
                        callbacks=callbacks,
                        validation_data=data_generator(valid_path),
                        validation_steps=validation_steps
                        )


if __name__ == '__main__':
    main()
