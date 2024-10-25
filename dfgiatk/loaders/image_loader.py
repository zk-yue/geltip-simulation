from abc import ABC, abstractmethod

import os
import random

import torch

from torchvision.datasets.folder import make_dataset
from os import path
import yaml
import cv2
import numpy as np
import matplotlib.pyplot as plt

from dfgiatk.ops.img import denormalize, cvt_batch, CVT_HWC2CHW


def _find_classes(dir):
    classes = [d.name for d in os.scandir(dir) if d.is_dir()]
    classes.sort()
    class_to_idx = {cls_name: i for i, cls_name in enumerate(classes)}
    return classes, class_to_idx


def get_samples(root, extensions=(".mp4", ".avi", ".webm")):
    _, class_to_idx = _find_classes(root)
    return make_dataset(root, class_to_idx, extensions=extensions)


class Labeler:

    def __init__(self, transform=None):
        self.transform = transform

    @abstractmethod
    def get_label(self, s):
        pass


class ClassificationLabeler(Labeler):

    def __init__(self, samples, transform=None, one_hot=False):
        super().__init__(transform=transform)

        self.classes = list({self.get_class(s): 1 for s in samples}.keys())
        self.classes.sort()

        self.one_hot = one_hot

    def get_class(self, s):
        return path.basename(path.dirname(s))

    def get_label(self, s):
        idx = self.classes.index(self.get_class(s))
        if self.one_hot:
            _1_hot = np.zeros((len(self.classes, )))
            _1_hot[idx] = 1
            return _1_hot
        return np.array(idx)


class LocalizationLabeler(Labeler):

    def __init__(self, transform=None, locations_path=None):
        super().__init__(transform=transform)
        self.locations = yaml.full_load(open(locations_path)) \
            if locations_path is not None else None

    def get_label(self, s):
        filename_w_extension = path.basename(s)
        file_name = filename_w_extension[: filename_w_extension.index('.')]
        folder = path.basename(path.dirname(s))
        if self.locations:
            return np.array([float(c) for c in self.locations[f'{folder}/{file_name}']], dtype=np.float32)
        return np.array([float(c) for c in file_name.split('_')], dtype=np.float32)


class NumpyMapsLabeler(Labeler):

    def __init__(self, base_path, transform=None):
        super().__init__(transform=transform)
        self.base_path = base_path

    def get_label(self, s):
        filename_w_extension = path.basename(s)
        file_name = filename_w_extension[: filename_w_extension.index('.')]
        folder = path.basename(path.dirname(s))
        m = np.load(path.join(self.base_path, folder, file_name + '.npy'))
        # m = np.swapaxes(m, 0, 1)
        # m = m[np.newaxis, ...]
        return m


class ImageLoader(Labeler):

    def __init__(self, transform=None):
        super().__init__(transform=transform)

    def get_label(self, s):
        img = cv2.imread(s)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        return img


class DatasetSampler(torch.utils.data.IterableDataset):
    def __init__(self,
                 samples,
                 loader=None,
                 labeler=None,
                 epoch_size=1,
                 batch_size=32,
                 random_sampling=True,
                 return_names=False,
                 device='cuda'):
        super(DatasetSampler).__init__()

        self.batch_size = batch_size or len(samples)
        self.epoch_size = epoch_size or len(samples)
        self.loader = loader
        self.labeler = labeler
        self.samples = samples
        self.random_sampling = random_sampling
        self.return_names = return_names
        self.device = device

    def get_sample(self, i):
        # Get random sample
        sample_path = random.choice(self.samples) if self.random_sampling else self.samples[i]

        return self.loader.get_label(sample_path), \
               self.labeler.get_label(sample_path), \
               sample_path

    def sample_batch(self):
        xs, ys, samples = list(zip(*[self.get_sample(i) for i in range(self.it, self.it + self.batch_size)]))
        xs, ys = np.array(xs), np.array(ys)

        if self.loader.transform is not None:
            xs = self.loader.transform(xs, samples=samples)

        if self.labeler.transform is not None:
            ys = self.labeler.transform(ys)

        x = torch.from_numpy(xs)
        y_true = torch.from_numpy(ys)

        if self.return_names:
            return x.to(self.device), y_true.to(self.device), samples

        return x.to(self.device), y_true.to(self.device)

    def __iter__(self):
        self.it = 0
        return self

    def __next__(self):
        if self.it >= self.epoch_size:
            raise StopIteration
        else:
            b = self.sample_batch()
            self.it += 1
            return b

    @staticmethod
    def load_from_yaml(yaml_path, prepend_path=None):
        return [(path.join(prepend_path, s) if prepend_path is not None else s)
                for s in yaml.full_load(open(yaml_path))]


def test():
    import imgaug.augmenters as iaa

    set = 'real_rgb'
    split_file = 'train_split.yaml'
    base_path = '/home/danfergo/Projects/PhD/geltip_simulation/geltip_dataset/dataset/'
    base = path.join('', set)

    samples = DatasetSampler.load_from_yaml(
        path.join(base_path, split_file),
        path.join(base_path, set)
    )

    # labeler = ClassificationLabeler(samples)
    # labeler = LocalizationLabeler()
    labeler = NumpyMapsLabeler(path.join(base_path, 'sim_depth_aligned'))

    def data_preparation(xs):
        xs = (cvt_batch(xs, CVT_HWC2CHW) / 255.0).astype(np.float32)
        return iaa.Sequential([
            iaa.Resize({"height": 120, "width": "keep-aspect-ratio"}),
            iaa.OneOf([
                iaa.Affine(rotate=0.1),
                iaa.AdditiveGaussianNoise(scale=0.7),
                iaa.Add(50, per_channel=True),
                iaa.Sharpen(alpha=0.5)
            ])
        ])(images=xs)

    loader = DatasetSampler(
        samples,
        labeler=labeler,
        transform=data_preparation
    )

    for x, y in loader:
        imgs = x.detach().cpu().numpy()
        imgs = np.swapaxes(imgs, 1, 2)
        imgs = np.swapaxes(imgs, 2, 3)

        for i in range(x.size()[0]):
            img = denormalize(imgs[i])
            plt.imshow(img)
            plt.show()

    # print(y.size())
    # batch_size=32
    # data = {"video": [], 'start': [], 'end': [], 'tensorsize': []}
    # print(batch[0].size())
    # print(batch)
    # for i in range(len(batch['path'])):
    # data['video'].append(batch['path'][i])
    # data['start'].append(batch['start'][i].item())
    # data['end'].append(batch['end'][i].item())
    # data['tensorsize'].append(batch['video'][i].size())


if __name__ == '__main__':
    test()
