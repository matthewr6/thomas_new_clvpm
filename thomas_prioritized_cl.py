import os
import sys
import os
import subprocess
import numpy as np
import nibabel as nib
from scipy import ndimage
from skimage import morphology

path = os.path.abspath(os.path.dirname(__file__))

template = os.path.join(path, 'template.nii.gz')
atlas = os.path.join(path, 'atlas_with_CL_VPM.nii.gz')

def warp_to_template(
        cost='CC',
        input_image='mWMn.nii.gz',
        iterations='30x90x20',
        warp_out='warps/mWMn'):
    os.makedirs(os.path.dirname(warp_out), exist_ok=True)
    build_warp = True
    if '--ignore-existing-warps' not in sys.argv and os.path.exists(warp_out + 'Affine.txt') and os.path.exists(warp_out + 'InverseWarp.nii.gz'):
        if '--use-existing-warps' in sys.argv:
            build_warp = False
        else:
            build_warp = 'y' == input('Warps exist.  Rebuild? [y/n] ').lower()
    if build_warp:
        cmd = 'ANTS 3 -m {}[{},{},1,5] -t SyN[0.25] -r Gauss[3,0] -o {} -i {} --use-Histogram-Matching --number-of-affine-iterations 10000x10000x10000x10000x10000 --MI-option 32x16000'.format(cost, template, input_image, warp_out, iterations)
        subprocess.check_call(cmd, shell=True)
    return warp_out

def apply_invwarp_to_atlas(
        base_image,
        warp_path,
        out_path):
    if os.path.dirname(out_path):
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

    if os.path.exists(out_path):
        print('Atlas in native space already exists')
        return out_path
    
    warp_cmd = 'WarpImageMultiTransform 3 {} {} -R {} -i {}Affine.txt {}InverseWarp.nii.gz --use-NN'.format(atlas, out_path, base_image, warp_path, warp_path)
    subprocess.check_call(warp_cmd, shell=True)
    return out_path

cl_vpm_fnames = {
    17: '17-CL.nii.gz',
    18: '18-VPM.nii.gz'
}
def merge_atlas(primary_fname, secondary_fname, out_path):
    """
    Merge two atlases together.  The primary atlas is preserved.  New ROIs in the secondary atlas are dilated and used to fill in the "cracks" of the primary atlas.  These should be two NIfTI paths.
    """
    background_values={0}
    primary = nib.load(primary_fname)
    primary.data = primary.get_fdata().astype(int)
    secondary = nib.load(secondary_fname)
    secondary.data = secondary.get_fdata().astype(int)
    # get all ROI values and remove background ROI
    labels_in_primary = set(np.unique(primary.data)) - background_values
    mask_primary = np.isin(primary.data, list(labels_in_primary))
    # keep only new ROIs, keep only voxels that are not primary atlas or background values
    mask_secondary = np.isin(secondary.data, list(labels_in_primary), invert=True) * np.isin(secondary.data, list(background_values), invert=True)

    new_nuclei = secondary.data * mask_secondary
    new_nuclei_values = set(np.unique(new_nuclei)) - background_values
    new_nuclei = morphology.dilation(new_nuclei, footprint=None)
    # new_nuclei = morphology.closing(new_nuclei, selem=np.ones((3, 3, 3)))
    merged_atlas = new_nuclei * np.invert(mask_primary) + primary.data * mask_primary
    for value in new_nuclei_values:
        nii = nib.Nifti1Pair(merged_atlas == value, primary.affine, header=primary.header)
        nib.save(nii, os.path.join(out_path, cl_vpm_fnames[value]))

def combine_vols(a_path, b_path, outpath):
    a = nib.load(a_path)
    b = nib.load(b_path)

    combined_data = a.get_fdata() + b.get_fdata()
    combined = nib.Nifti1Image(combined_data, affine=a.affine, header=a.header)
    if os.path.dirname(outpath):
        os.makedirs(os.path.dirname(outpath), exist_ok=True)
    nib.save(combined, outpath)
    return outpath

def flip_image(infile='mWMn.nii.gz', outfile='temp-right/mWMn.nii.gz'):
    os.makedirs(os.path.dirname(outfile), exist_ok=True)
    vol = nib.load(infile)
    flipped_data = np.flip(vol.get_fdata(), 0)
    flipped_vol = nib.Nifti1Image(flipped_data, affine=vol.affine, header=vol.header)
    nib.save(flipped_vol, outfile)
    return outfile

def main():
    warp_path = warp_to_template(input_image='WMn.nii.gz', warp_out='temp-left/warps/WMn')
    warped_atlas = apply_invwarp_to_atlas(base_image='WMn.nii.gz', warp_path=warp_path, out_path='temp-left/CLVPM-atlas-native.nii.gz')
    merge_atlas('left/multiatlas_full.nii.gz', warped_atlas, 'left')

    flipped_image = flip_image(infile='WMn.nii.gz')

    warp_path = warp_to_template(input_image=flipped_image, warp_out='temp-right/warps/WMn')
    warped_atlas = apply_invwarp_to_atlas(base_image=flipped_image, warp_path=warp_path, out_path='temp-right/CLVPM-atlas-native.nii.gz')
    flipped_warped_atlas = flip_image(infile=warped_atlas, outfile='temp-right/CLVPM-atlas-native-corrected.nii.gz')
    merge_atlas('right/multiatlas_full.nii.gz', flipped_warped_atlas, 'right')

    # combine_vols('left/CLVPM-multiatlas.nii.gz', 'right/CLVPM-multiatlas.nii.gz', 'CLVPM-multiatlas.nii.gz')

main()