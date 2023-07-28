import os
import sys
import subprocess
import numpy as np
import nibabel as nib

a = sys.argv[1]
b = sys.argv[2]
out = sys.argv[3]

def combine_vols(a_path, b_path, outpath):
    a = nib.load(a_path)
    b = nib.load(b_path)

    combined_data = a.get_fdata() + b.get_fdata()
    combined = nib.Nifti1Image(combined_data, affine=a.affine, header=a.header)
    if os.path.dirname(outpath):
        os.makedirs(os.path.dirname(outpath), exist_ok=True)
    nib.save(combined, outpath)
    return outpath

combine_vols(a, b, out)
