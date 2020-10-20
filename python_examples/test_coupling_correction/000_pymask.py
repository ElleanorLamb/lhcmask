import os
import sys
import pickle

import numpy as np

from config import python_parameters, mask_parameters, knob_parameters


#####################################################
# Read general configurations and setup envirnoment #
#####################################################

mode = python_parameters['mode']
tol_beta = python_parameters['tol_beta']
tol_sep = python_parameters['tol_sep']
flat_tol = python_parameters['tol_co_flatness']
links = python_parameters['links']
optics_file = python_parameters['optics_file']
check_betas_at_ips = python_parameters['check_betas_at_ips']
check_separations_at_ips = python_parameters['check_separations_at_ips']
save_intermediate_twiss = python_parameters['save_intermediate_twiss']
force_leveling= python_parameters['force_leveling']

# Make links
for kk in links.keys():
    if os.path.exists(kk):
        os.remove(kk)
    os.symlink(os.path.abspath(links[kk]), kk)

# Execute customization script if present
os.system('bash customization.bash')

# Import pymask
sys.path.append('./modules')
import pymask as pm
import pymask.coupling as pc
import pymask.luminosity as lumi

# Import user-defined optics-specific tools
import optics_specific_tools as ost

######################################
# Check parameters and activate mode #
######################################

# Check and load parameters 
pm.checks_on_parameter_dict(mask_parameters)

# Define configuration
(beam_to_configure, sequences_to_check, sequence_to_track, generate_b4_from_b2,
    track_from_b4_mad_instance, enable_bb_python, enable_bb_legacy,
    force_disable_check_separations_at_ips,
    ) = pm.get_pymask_configuration(mode)

if force_disable_check_separations_at_ips:
    check_separations_at_ips = False

if not(enable_bb_legacy) and not(enable_bb_python):
    mask_parameters['par_on_bb_switch'] = 0.


########################
# Build MAD-X instance #
########################

# Start mad
Madx = pm.Madxp
mad = Madx()

# Build sequence
ost.build_sequence(mad, beam=beam_to_configure)

# Apply optics
ost.apply_optics(mad, optics_file=optics_file)

# Pass parameters to mad
mad.set_variables_from_dict(params=mask_parameters)

# Prepare auxiliary mad variables
mad.call("modules/submodule_01a_preparation.madx")

# Attach beams to sequences
mad.call("modules/submodule_01b_beam.madx")

# Set optics-specific knobs
ost.set_optics_specific_knobs(mad, knob_parameters, mode)

# Synthesisze knobs
mad.call('modules/submodule_04_1b_save_references.madx')
mad.call('modules/submodule_04a_s1_prepare_nom_twiss_table.madx')
mad.call('modules/submodule_04e_s1_synthesize_knobs.madx')


cmrskew_test = 1e-4
cmiskew_test = 0.

# Introduce large coupling for testing
mad.globals.cmrskew = cmrskew_test
mad.globals.cmiskew = cmiskew_test

# Test old approach
mad.call('modules/submodule_05b_coupling.madx')
cmrskew_legacy = mad.globals.cmrskew
cmiskew_legacy = mad.globals.cmiskew
cta_legacy = pc.coupling_measurement(mad,
        qx_integer=62., qy_integer=60.,
        qx_fractional=.31, qy_fractional=.32,
        tune_knob1_name='kqtf.b1', tune_knob2_name='kqtd.b1',
        sequence_name='lhcb1', skip_use=False)



# Test new approach
mad.globals.cmrskew = cmrskew_test
mad.globals.cmiskew = cmiskew_test

pc.coupling_correction(mad, n_iterations=2,
        qx_integer=62., qy_integer=60.,
        qx_fractional=.31, qy_fractional=.32,
        tune_knob1_name='kqtf.b1', tune_knob2_name='kqtd.b1',
        cmr_knob_name = 'cmrskew', cmi_knob_name = 'cmiskew',
        sequence_name='lhcb1', skip_use=False)
cmrskew_new = mad.globals.cmrskew
cmiskew_new = mad.globals.cmiskew
cta_new = pc.coupling_measurement(mad,
        qx_integer=62., qy_integer=60.,
        qx_fractional=.31, qy_fractional=.32,
        tune_knob1_name='kqtf.b1', tune_knob2_name='kqtd.b1',
        sequence_name='lhcb1', skip_use=False)

print(f'cmrskew_legacy = {cmrskew_legacy}')
print(f'cmrskew_new = {cmrskew_new}')
print(f'cmiskew_legacy = {cmiskew_legacy}')
print(f'cmiskew_new = {cmiskew_new}')
print(f'cta_legacy = {cta_legacy}')
print(f'cta_new = {cta_new}')
