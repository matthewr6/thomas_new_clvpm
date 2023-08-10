#!/bin/bash

scriptpath=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )

if [ ! -f "left/multiatlas_full.nii.gz" ]; then
    cd left/
    python3 $scriptpath/form_multiatlas.py multiatlas.nii.gz
    python3 $scriptpath/uncrop.py multiatlas.nii.gz multiatlas_full.nii.gz mask_inp.nii.gz
    cd ../
fi

if [ ! -f "right/multiatlas_full.nii.gz" ]; then
    cd right/
    python3 $scriptpath/form_multiatlas.py multiatlas.nii.gz
    python3 $scriptpath/uncrop.py multiatlas.nii.gz multiatlas_full.nii.gz mask_inp.nii.gz
    cd ../
fi

python3 $scriptpath/combine_hemispheres.py left/multiatlas_full.nii.gz right/multiatlas_full.nii.gz multiatlas.nii.gz
python3 $scriptpath/thomas_prioritized_cl.py --use-existing-warps

