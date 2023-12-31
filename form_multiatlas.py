#!/usr/bin/env python
"""
Create multi-atlas from nuclei and evaluate overlap against original truth labels.
"""


import os
import sys
import re
import shelve
import tempfile
import argparse
from collections import OrderedDict
import subprocess
import signal
import multiprocessing.pool
import functools


class PoolWrapper(object):
    """
    Wraps a function to permit KeyboardInterrupt with a multiprocessing.Pool without traceback.
    Graceful exit will finish the job first before quitting, may only work in Unix-like system.
    Supports unpacking of arguments from tuples or keywords from dictionaries.
    """
    def __init__(self, func, graceful=False, unpack=True):
        self.func = func
        self.graceful = graceful
        self.unpack = unpack

    def __call__(self, args):
        if self.graceful:
            s = signal.signal(signal.SIGINT, signal.SIG_IGN)
            result = self._execute(args)
            signal.signal(signal.SIGINT, s)
            return result
        else:
            try:
                return self._execute(args)
            except KeyboardInterrupt:
                # Don't print out traceback.
                pass

    def _execute(self, args):
        if self.unpack:
            if isinstance(args, dict):
                return self.func(**args)
            return self.func(*args)
        else:
            return self.func(args)


class BetterPool(multiprocessing.pool.Pool):
    """
    A modification of multiprocessing.pool.Pool with map methods that properly receive keyboard
    interrupts.  By default, it will unpack tuple or dictionary arguments for the function call.
    """
    def _wrap(self, func, iterable):
        if iterable:
            if not isinstance(func, PoolWrapper):
                if isinstance(iterable[0], tuple) or isinstance(iterable[0], dict):
                    func = PoolWrapper(func, unpack=True)
                else:
                    func = PoolWrapper(func, unpack=False)
        return func

    def map_async(self, func, iterable, *args, **kwargs):
        func = self._wrap(func, iterable)
        return super(BetterPool, self).map_async(func, iterable, *args, **kwargs)

    def map(self, func, iterable, *args, **kwargs):
        p = self.map_async(func, iterable, *args, **kwargs)
        try:
            return p.get(0xFFFFFF)
        except KeyboardInterrupt:
            self.terminate()
            raise


def command(cmd, echo=False, verbose=False, debug=False, suppress=False, env=None):
    # sp_cmd = cmd.split(' ')
    if echo:
        print(cmd)
        return
    if verbose:
        print('Executing: %s' % cmd)
    if debug:
        # Workaround for Python 2/3
        try:
            input = raw_input
        except NameError:
            pass
        print('About to run: %s' % cmd)
        if eval(input('  Type n to skip')) == 'n':
            return
    if suppress:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True, env=env)
        stdout, stderr = p.communicate()
        if stderr:
            print(stderr)
        return p.returncode
    # return subprocess.call(sp_cmd)
    return subprocess.call(cmd, shell=True, env=env)


def overlap_c3d(im1, im2, label=1):
    # Compute volumes and overlap
    x = os.popen('c3d %s %s -overlap %s' % (im1, im2, label)).read()
    return [float(el) for el in x.split(', ')[1:4]]


def dice_c3d(im1, im2, label=1):
    # Compute Dice overlap
    x = os.popen('c3d %s %s -overlap %s' % (im1, im2, label)).read()
    try:
        return float(x.split(', ')[-2])
    except ValueError:
        print(x)
        raise


def split_multiatlas(atlas, output_prefix, pool=None):
    """
    Take a multi-atlas with many ROIs and split it into binary masks for each ROI.

    output_prefix can be a container with integer index keys as in the atlas image
    and values the full output path.
    """
    N = int(os.popen('MeasureMinMaxMean 3 %s' % atlas).read().split('[', 1)[-1].split(']', 1)[0])
    if pool is None:
        pool = BetterPool()
    cmds = []
    for idx in range(N):
        if isinstance(output_prefix, str):
            output = '%s-%s.nii.gz' % (output_prefix, idx)
        else:
            try:
                output = output_prefix[idx]
            except (IndexError, KeyError):
                print(('Skipping %d' % idx))
                continue
        cmds.append('ThresholdImage 3 %s %s %d %d' % (atlas, output, idx, idx))
    pool.map(command, cmds)


def cmp(a, b):
    return (a > b) - (a < b) 
    
class CompareOverlap(object):
    def __init__(self, labels, pool=None):
        self.volume = {}
        self.overlap = {}
        if pool is None:
            pool = BetterPool()
        # TODO refactor using knowledge that it's a symmetric matrix of values
        # Determine pairwise overlap
        for label1 in labels:
            overlap_params = []
            for label2 in labels:
                overlap_params.append((label1, label2))
            datum = pool.map(overlap_c3d, overlap_params)
            vol1, vol2, over = list(zip(*datum))
            # This overwrites same value a lot, bit redundant
            self.volume = dict(list(zip(labels, vol2)))
            self.overlap[label1] = dict(list(zip(labels, over)))

    def __call__(self, label1, label2):
        overlap = self.overlap[label1][label2]
        vol1 = self.volume[label1]
        vol2 = self.volume[label2]
        # Broadly we want to sort so that the smaller nuclei gets priority, i.e. less percent of it is overwritten by overlap
        try:
            return cmp(overlap/vol1, overlap/vol2)
        except ZeroDivisionError:
            print('Maybe label was not 0/1?')
            print((label1, vol1))
            print((label2, vol2))
            raise


# Approximately Thomas's method, can debate about order of some elements, like VLP and MTT/VA
# ['2-AV', '4-VA', '5-VLa', '6-VLP', '7-VPL', '8-Pul', '9-LGN', '10-MGN', '11-CM', '12-MD-Pf', '13-Hb', '14-MTT']
# methods = {
#     'Thomas': ['8-Pul', '11-CM', '12-MD-Pf', '4-VA', '14-MTT', '2-AV', '13-Hb', '6-VLP', '5-VLa', '7-VPL', '9-LGN', '10-MGN'],
#     'Fixed_Metric': ['2-AV', '6-VLP', '4-VA', '5-VLa', '8-Pul', '7-VPL', '9-LGN', '10-MGN', '12-MD-Pf', '11-CM', '13-Hb', '14-MTT'],
# }
DEFAULT_ROIS = ['2-AV', '4-VA', '5-VLa', '6-VLP', '7-VPL', '8-Pul', '9-LGN', '10-MGN', '11-CM', '12-MD-Pf', '13-Hb', '14-MTT']

find_num = re.compile('[0-9]+')
parser = argparse.ArgumentParser(description='Merge a set of binary masks into a single integer-leveled atlas.')
parser.add_argument('--method', choices=['Numerical', 'Metric'], default='Metric', help='method to combine masks together.  Numerical to use the index when files are of the format "index#-*.nii.gz", higher index numbers take precedence over lower ones where they overlap.  Metric to compute dice overlap and determine a precedence that leads to the minimum change in dice (generally favors smaller ROIs).')
parser.add_argument('output_path', help='the output atlas NIfTI file.')
parser.add_argument('-p', '--processes', nargs='?', default=None, const=None, type=int, help='number of parallel processes to use.  If unspecified, automatically set to number of CPUs.')
# parser.add_argument('-v', '--verbose', action='store_true', help='verbose mode')
# parser.add_argument('-d', '--debug', action='store_true', help='debug mode, interactive prompts')
# parser.add_argument('-R', '--right', action='store_true', help='segment right thalamus')

if __name__ == '__main__':
    args = parser.parse_args()
    pool = BetterPool(args.processes)
    method = args.method
    out = args.output_path
    labels = DEFAULT_ROIS
    if method == 'Numerical':
        print('Using the input order')
        method_labels = labels
    elif method == 'Metric':
        # Use overlap metric based comparison
        print('Calculating overlap metric weighted by volume')
        compare = CompareOverlap(labels, pool)
        method_labels = sorted(labels, key=functools.cmp_to_key(compare))
    label_numbers = dict()
    for i, label in enumerate(labels):
        label_num = find_num.search(os.path.basename(label))
        if label_num is None:
            label_numbers[label] = i
        else:
            label_numbers[label] = label_num.group(0)
    # Check that all numbers are unique
    try:
        assert len(set(label_numbers.values())) == len(list(label_numbers.values()))
    except AssertionError:
        print('Make sure the ID number is at the beginning of the filename.')
        print(label_numbers)
        raise

    print('Creating atlas')
    try:
        temp_file = tempfile.NamedTemporaryFile(suffix='.nii.gz', delete=True)
        # CreateImage imageDimension referenceImage outputImage constant [random?]
        os.system('CreateImage 3 %s %s 0' % (labels[0], out))
        # overadd gives priority to labels later in list, addtozero gives priority to first or reversed(labels)
        # TODO parallelize over fslmaths
        for label in method_labels:
            print(label)
            # print label
            # Remake ROI with the correct integer label
            os.system('fslmaths %s -bin -mul %s %s' % (label, label_numbers[label], temp_file.name))
            # ImageMath ImageDimension <OutputImage.ext> [operations and inputs] <Image1.ext> <Image2.ext>
            #   addtozero        : add image-b to image-a only over points where image-a has zero values
            #   overadd        : replace image-a pixel with image-b pixel if image-b pixel is non-zero
            os.system('ImageMath 3 %s overadd %s %s' % (out, out, temp_file.name))
    finally:
        temp_file.close()

    # Evaluate dice of combined atlas vs original independent ROIs
    print('Evaluating atlas')
    temp_files = []
    cmds = []
    dice_params = []
    atlas = out
    try:
        for label, label_num in list(label_numbers.items()):
            temp_file = tempfile.NamedTemporaryFile(suffix='.nii.gz', delete=True)
            temp_files.append(temp_file)
            cmd = 'fslmaths %s -bin -mul %s %s' % (label, label_num, temp_file.name)
            cmds.append(cmd)
            dice_params.append((temp_file.name, atlas, label_num))
        pool.map(os.system, cmds)
        # TODO fully parallelize, don't join before collecting dice
        dices = pool.map(dice_c3d, dice_params)
    finally:
        for temp_file in temp_files:
            temp_file.close()

    # Output to screen
    scores = OrderedDict(list(zip(labels, dices)))
    print('Label\tDice')
    for label, score in list(scores.items()):
        print(('%s\t%.6g' % (label, score)))
    db = shelve.open(out+'.shelve')
    db.update(scores)
    db.close()
